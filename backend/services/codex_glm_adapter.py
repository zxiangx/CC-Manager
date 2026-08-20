"""Translate Codex Responses payloads to Apex Anthropic Messages for GLM.

Codex 0.145 only supports the Responses wire API. Apex currently exposes its
GLM models through Chat Completions and Anthropic Messages, while `/responses`
returns `not implemented`. This module keeps the native Codex harness intact by
performing a bounded, model-gated conversion at CCM's existing loopback proxy.
"""

from __future__ import annotations

import json
import time
from typing import Any


DEFAULT_MAX_TOKENS = 32_768
MAX_MAX_TOKENS = 131_072
MAX_ITEMS = 4096
MAX_TOOLS = 256
MAX_TEXT_BYTES = 32 * 1024 * 1024
# Apex's Anthropic-compatible endpoint accepts client-defined tools, but it
# cannot execute OpenAI-hosted Responses tools.  Codex includes web_search in
# its default catalog even when a turn never asks for it, so omit that one
# known hosted capability while preserving every local harness tool.
UNSUPPORTED_HOSTED_TOOL_TYPES = frozenset({"web_search"})


class CodexGlmAdapterError(RuntimeError):
    """A GLM request or response cannot be converted without ambiguity."""


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _bounded_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise CodexGlmAdapterError(f"Invalid {field}")
    if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        raise CodexGlmAdapterError(f"{field} is too large")
    return value


def _content_blocks(value: Any, *, output: bool = False) -> list[dict[str, Any]]:
    if isinstance(value, str):
        return [{"type": "text", "text": _bounded_text(value, field="message text")}]
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise CodexGlmAdapterError("Invalid message content")
    blocks: list[dict[str, Any]] = []
    allowed = {"text", "output_text"} if output else {"text", "input_text"}
    for part in value:
        if not isinstance(part, dict) or part.get("type") not in allowed:
            raise CodexGlmAdapterError("Unsupported message content part")
        blocks.append({
            "type": "text",
            "text": _bounded_text(part.get("text"), field="message text"),
        })
    return blocks


def _append_message(
    messages: list[dict[str, Any]],
    role: str,
    blocks: list[dict[str, Any]],
) -> None:
    if not blocks:
        return
    if messages and messages[-1]["role"] == role:
        messages[-1]["content"].extend(blocks)
    else:
        messages.append({"role": role, "content": blocks})


def _tool_definition(tool: dict[str, Any]) -> tuple[dict[str, Any], str]:
    kind = tool.get("type")
    nested = tool.get("function") if isinstance(tool.get("function"), dict) else None
    if kind == "function":
        source = nested or tool
        name = source.get("name")
        description = source.get("description") or ""
        schema = source.get("parameters", {"type": "object", "properties": {}})
        result_kind = "function"
    elif kind == "custom":
        name = tool.get("name")
        description = tool.get("description") or ""
        schema = {
            "type": "object",
            "properties": {"input": {"type": "string"}},
            "required": ["input"],
            "additionalProperties": False,
        }
        result_kind = "custom"
    else:
        raise CodexGlmAdapterError("Unsupported Codex tool type")
    if not isinstance(name, str) or not name or len(name) > 128:
        raise CodexGlmAdapterError("Invalid Codex tool name")
    if not isinstance(description, str) or len(description.encode()) > 64 * 1024:
        raise CodexGlmAdapterError("Invalid Codex tool description")
    if not isinstance(schema, dict):
        raise CodexGlmAdapterError("Invalid Codex tool schema")
    return ({
        "name": name,
        "description": description,
        "input_schema": schema,
    }, result_kind)


def _tool_input(item: dict[str, Any], kind: str) -> dict[str, Any]:
    if kind == "custom":
        return {"input": _bounded_text(item.get("input", ""), field="custom tool input")}
    raw = item.get("arguments", "{}")
    if isinstance(raw, dict):
        return raw
    raw = _bounded_text(raw, field="function arguments")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CodexGlmAdapterError("Invalid function arguments") from exc
    if not isinstance(value, dict):
        raise CodexGlmAdapterError("Function arguments must be an object")
    return value


def responses_request_to_anthropic(
    body: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Convert one Codex Responses request into an Apex Messages payload."""

    if not isinstance(body, dict):
        raise CodexGlmAdapterError("Invalid Responses request")
    model = body.get("model")
    if not isinstance(model, str) or not model.lower().startswith("glm-"):
        raise CodexGlmAdapterError("Unsupported GLM model")

    raw_tools = body.get("tools") or []
    if not isinstance(raw_tools, list) or len(raw_tools) > MAX_TOOLS:
        raise CodexGlmAdapterError("Invalid Codex tools")
    tools: list[dict[str, Any]] = []
    tool_kinds: dict[str, str] = {}
    for raw_tool in raw_tools:
        if not isinstance(raw_tool, dict):
            raise CodexGlmAdapterError("Invalid Codex tool")
        if raw_tool.get("type") in UNSUPPORTED_HOSTED_TOOL_TYPES:
            continue
        converted, kind = _tool_definition(raw_tool)
        if converted["name"] in tool_kinds:
            raise CodexGlmAdapterError("Duplicate Codex tool name")
        tool_kinds[converted["name"]] = kind
        tools.append(converted)

    instructions = body.get("instructions")
    system_parts: list[str] = []
    if instructions is not None:
        system_parts.append(_bounded_text(instructions, field="instructions"))

    raw_input = body.get("input", [])
    if isinstance(raw_input, str):
        raw_input = [{"type": "message", "role": "user", "content": raw_input}]
    if not isinstance(raw_input, list) or len(raw_input) > MAX_ITEMS:
        raise CodexGlmAdapterError("Invalid Responses input")

    messages: list[dict[str, Any]] = []
    call_kinds: dict[str, str] = {}
    for item in raw_input:
        if not isinstance(item, dict):
            raise CodexGlmAdapterError("Invalid Responses input item")
        item_type = item.get("type", "message" if "role" in item else None)
        if item_type == "message":
            role = item.get("role")
            if role in {"system", "developer"}:
                blocks = _content_blocks(item.get("content"))
                system_parts.extend(block["text"] for block in blocks)
            elif role == "user":
                _append_message(messages, "user", _content_blocks(item.get("content")))
            elif role == "assistant":
                _append_message(
                    messages,
                    "assistant",
                    _content_blocks(item.get("content"), output=True),
                )
            else:
                raise CodexGlmAdapterError("Unsupported message role")
            continue
        if item_type in {"function_call", "custom_tool_call"}:
            kind = "custom" if item_type == "custom_tool_call" else "function"
            name = item.get("name")
            call_id = item.get("call_id") or item.get("id")
            if not isinstance(name, str) or name not in tool_kinds:
                raise CodexGlmAdapterError("Unknown tool call name")
            if tool_kinds[name] != kind:
                raise CodexGlmAdapterError("Tool call type mismatch")
            if not isinstance(call_id, str) or not call_id:
                raise CodexGlmAdapterError("Invalid tool call id")
            call_kinds[call_id] = kind
            _append_message(messages, "assistant", [{
                "type": "tool_use",
                "id": call_id,
                "name": name,
                "input": _tool_input(item, kind),
            }])
            continue
        if item_type in {"function_call_output", "custom_tool_call_output"}:
            call_id = item.get("call_id")
            expected = (
                "custom" if item_type == "custom_tool_call_output" else "function"
            )
            if not isinstance(call_id, str) or call_kinds.get(call_id) != expected:
                raise CodexGlmAdapterError("Unmatched tool result")
            output = item.get("output", "")
            if not isinstance(output, str):
                output = _compact_json(output)
            _append_message(messages, "user", [{
                "type": "tool_result",
                "tool_use_id": call_id,
                "content": _bounded_text(output, field="tool result"),
            }])
            continue
        if item_type in {"reasoning", "compaction"}:
            # Provider-specific opaque reasoning/compaction state cannot be
            # replayed to GLM. Codex still supplies the visible conversation.
            continue
        raise CodexGlmAdapterError("Unsupported Responses input item")

    if not messages:
        raise CodexGlmAdapterError("Responses input has no messages")
    max_tokens = body.get("max_output_tokens", DEFAULT_MAX_TOKENS)
    if max_tokens is None:
        max_tokens = DEFAULT_MAX_TOKENS
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool):
        raise CodexGlmAdapterError("Invalid max_output_tokens")
    max_tokens = min(max(1, max_tokens), MAX_MAX_TOKENS)

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if system_parts:
        payload["system"] = "\n\n".join(part for part in system_parts if part)
    if tools:
        payload["tools"] = tools
        raw_choice = body.get("tool_choice")
        if raw_choice == "required":
            payload["tool_choice"] = {"type": "any"}
        elif raw_choice == "none":
            payload["tool_choice"] = {"type": "none"}
        else:
            payload["tool_choice"] = {"type": "auto"}
    return payload, tool_kinds


def _response_shell(
    response_id: str,
    model: str,
    *,
    status: str,
    output: list[dict[str, Any]],
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": status,
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "model": model,
        "output": output,
        "parallel_tool_calls": True,
        "previous_response_id": None,
        "service_tier": "default",
        "usage": usage,
    }


def _sse(events: list[dict[str, Any]]) -> bytes:
    return "".join(
        f"event: {event['type']}\ndata: {_compact_json(event)}\n\n"
        for event in events
    ).encode("utf-8")


def anthropic_message_to_responses_sse(
    message: dict[str, Any],
    *,
    tool_kinds: dict[str, str],
) -> bytes:
    """Convert one complete Apex Messages response to Responses SSE."""

    if not isinstance(message, dict):
        raise CodexGlmAdapterError("Invalid Apex message response")
    response_id = message.get("id")
    model = message.get("model")
    content = message.get("content")
    if not isinstance(response_id, str) or not response_id:
        raise CodexGlmAdapterError("Invalid Apex response id")
    if not isinstance(model, str) or not model.lower().startswith("glm-"):
        raise CodexGlmAdapterError("Invalid Apex response model")
    if not isinstance(content, list) or len(content) > MAX_ITEMS:
        raise CodexGlmAdapterError("Invalid Apex response content")

    usage_raw = message.get("usage") if isinstance(message.get("usage"), dict) else {}
    input_tokens = int(usage_raw.get("input_tokens") or 0)
    output_tokens = int(usage_raw.get("output_tokens") or 0)
    cached_tokens = int(usage_raw.get("cache_read_input_tokens") or 0)
    usage = {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": cached_tokens},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": input_tokens + output_tokens,
    }
    events: list[dict[str, Any]] = []
    sequence = 0

    def emit(event_type: str, **fields: Any) -> None:
        nonlocal sequence
        events.append({"type": event_type, "sequence_number": sequence, **fields})
        sequence += 1

    emit(
        "response.created",
        response=_response_shell(
            response_id, model, status="in_progress", output=[], usage=None,
        ),
    )
    emit(
        "response.in_progress",
        response=_response_shell(
            response_id, model, status="in_progress", output=[], usage=None,
        ),
    )
    output: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            raise CodexGlmAdapterError("Invalid Apex content block")
        block_type = block.get("type")
        output_index = len(output)
        if block_type == "text":
            text = _bounded_text(block.get("text"), field="Apex response text")
            item_id = f"msg_{response_id}_{output_index}"
            initial = {
                "id": item_id,
                "type": "message",
                "status": "in_progress",
                "role": "assistant",
                "content": [],
            }
            emit("response.output_item.added", output_index=output_index, item=initial)
            part = {"type": "output_text", "annotations": [], "text": ""}
            emit(
                "response.content_part.added",
                item_id=item_id,
                output_index=output_index,
                content_index=0,
                part=part,
            )
            emit(
                "response.output_text.delta",
                item_id=item_id,
                output_index=output_index,
                content_index=0,
                delta=text,
                logprobs=[],
            )
            done_part = {"type": "output_text", "annotations": [], "text": text}
            emit(
                "response.output_text.done",
                item_id=item_id,
                output_index=output_index,
                content_index=0,
                text=text,
                logprobs=[],
            )
            emit(
                "response.content_part.done",
                item_id=item_id,
                output_index=output_index,
                content_index=0,
                part=done_part,
            )
            final_item = {
                **initial,
                "status": "completed",
                "content": [done_part],
            }
            emit("response.output_item.done", output_index=output_index, item=final_item)
            output.append(final_item)
            continue
        if block_type == "tool_use":
            call_id = block.get("id")
            name = block.get("name")
            tool_input = block.get("input")
            if (
                not isinstance(call_id, str)
                or not call_id
                or not isinstance(name, str)
                or name not in tool_kinds
                or not isinstance(tool_input, dict)
            ):
                raise CodexGlmAdapterError("Invalid Apex tool_use block")
            kind = tool_kinds[name]
            if kind == "custom":
                raw_input = tool_input.get("input")
                if not isinstance(raw_input, str):
                    raw_input = _compact_json(tool_input)
                initial = {
                    "id": call_id,
                    "type": "custom_tool_call",
                    "status": "in_progress",
                    "call_id": call_id,
                    "name": name,
                    "input": "",
                }
                emit("response.output_item.added", output_index=output_index, item=initial)
                emit(
                    "response.custom_tool_call_input.delta",
                    item_id=call_id,
                    output_index=output_index,
                    delta=raw_input,
                )
                emit(
                    "response.custom_tool_call_input.done",
                    item_id=call_id,
                    output_index=output_index,
                    input=raw_input,
                )
                final_item = {**initial, "status": "completed", "input": raw_input}
            else:
                arguments = _compact_json(tool_input)
                initial = {
                    "id": call_id,
                    "type": "function_call",
                    "status": "in_progress",
                    "call_id": call_id,
                    "name": name,
                    "arguments": "",
                }
                emit("response.output_item.added", output_index=output_index, item=initial)
                emit(
                    "response.function_call_arguments.delta",
                    item_id=call_id,
                    output_index=output_index,
                    delta=arguments,
                )
                emit(
                    "response.function_call_arguments.done",
                    item_id=call_id,
                    output_index=output_index,
                    name=name,
                    arguments=arguments,
                )
                final_item = {
                    **initial,
                    "status": "completed",
                    "arguments": arguments,
                }
            emit("response.output_item.done", output_index=output_index, item=final_item)
            output.append(final_item)
            continue
        if block_type in {"thinking", "redacted_thinking"}:
            continue
        raise CodexGlmAdapterError("Unsupported Apex content block")

    emit(
        "response.completed",
        response=_response_shell(
            response_id, model, status="completed", output=output, usage=usage,
        ),
    )
    return _sse(events)
