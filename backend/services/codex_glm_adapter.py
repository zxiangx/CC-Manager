"""Translate Codex Responses payloads to Apex Anthropic Messages for GLM.

Codex 0.145 only supports the Responses wire API. Apex currently exposes its
GLM models through Chat Completions and Anthropic Messages, while `/responses`
returns `not implemented`. This module keeps the native Codex harness intact by
performing a bounded, model-gated conversion at CCM's existing loopback proxy.
"""

from __future__ import annotations

import json
import hashlib
import re
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
_ANTHROPIC_TOOL_NAME_RE = re.compile(r"[^A-Za-z0-9_-]")


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


def _namespace_tool_name(namespace: str, name: str) -> str:
    """Build a bounded Anthropic name while retaining a reversible route map."""

    if not namespace or len(namespace) > 128 or not name or len(name) > 128:
        raise CodexGlmAdapterError("Invalid Codex namespace tool name")
    readable = _ANTHROPIC_TOOL_NAME_RE.sub("_", f"{namespace}__{name}")
    if len(readable) <= 128:
        return readable
    digest = hashlib.sha256(f"{namespace}\0{name}".encode()).hexdigest()[:16]
    suffix = _ANTHROPIC_TOOL_NAME_RE.sub("_", name)[-96:]
    return f"namespace_{digest}__{suffix}"[:128]


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
    tool_kinds: dict[str, Any] = {}
    for raw_tool in raw_tools:
        if not isinstance(raw_tool, dict):
            raise CodexGlmAdapterError("Invalid Codex tool")
        if raw_tool.get("type") in UNSUPPORTED_HOSTED_TOOL_TYPES:
            continue
        if raw_tool.get("type") == "namespace":
            namespace = raw_tool.get("name")
            namespace_description = raw_tool.get("description") or ""
            nested_tools = raw_tool.get("tools")
            if (
                not isinstance(namespace, str)
                or not isinstance(namespace_description, str)
                or not isinstance(nested_tools, list)
            ):
                raise CodexGlmAdapterError("Invalid Codex tool namespace")
            for nested_tool in nested_tools:
                if not isinstance(nested_tool, dict):
                    raise CodexGlmAdapterError("Invalid Codex namespace tool")
                converted, kind = _tool_definition(nested_tool)
                if kind != "function":
                    raise CodexGlmAdapterError(
                        "Unsupported Codex namespace tool type"
                    )
                original_name = converted["name"]
                upstream_name = _namespace_tool_name(namespace, original_name)
                if upstream_name in tool_kinds:
                    raise CodexGlmAdapterError("Duplicate Codex tool name")
                description_parts = [
                    part
                    for part in (namespace_description, converted["description"])
                    if part
                ]
                converted["name"] = upstream_name
                converted["description"] = "\n\n".join(description_parts)
                tool_kinds[upstream_name] = {
                    "kind": "function",
                    "namespace": namespace,
                    "name": original_name,
                }
                tools.append(converted)
                if len(tools) > MAX_TOOLS:
                    raise CodexGlmAdapterError("Too many Codex namespace tools")
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
            namespace = item.get("namespace")
            call_id = item.get("call_id") or item.get("id")
            lookup_name = (
                _namespace_tool_name(namespace, name)
                if (
                    kind == "function"
                    and isinstance(namespace, str)
                    and isinstance(name, str)
                )
                else name
            )
            route = tool_kinds.get(lookup_name) if isinstance(lookup_name, str) else None
            route_kind = route.get("kind") if isinstance(route, dict) else route
            if not isinstance(name, str) or route is None:
                raise CodexGlmAdapterError("Unknown tool call name")
            if route_kind != kind:
                raise CodexGlmAdapterError("Tool call type mismatch")
            if not isinstance(call_id, str) or not call_id:
                raise CodexGlmAdapterError("Invalid tool call id")
            call_kinds[call_id] = kind
            _append_message(messages, "assistant", [{
                "type": "tool_use",
                "id": call_id,
                "name": lookup_name,
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
        "stream": True,
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


class AnthropicMessagesStreamAdapter:
    """Incrementally translate Anthropic Messages SSE into Responses SSE."""

    def __init__(self, *, tool_kinds: dict[str, Any]):
        self.tool_kinds = tool_kinds
        self.started = False
        self.completed = False
        self.response_id = ""
        self.model = ""
        self.sequence = 0
        self.blocks: dict[int, dict[str, Any]] = {}
        self.output: list[dict[str, Any]] = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_tokens = 0

    def _emit(self, event_type: str, **fields: Any) -> dict[str, Any]:
        event = {
            "type": event_type,
            "sequence_number": self.sequence,
            **fields,
        }
        self.sequence += 1
        return event

    @staticmethod
    def _token_count(value: Any, *, field: str) -> int:
        if value is None:
            return 0
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise CodexGlmAdapterError(f"Invalid {field}")
        return value

    def _usage(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "input_tokens_details": {"cached_tokens": self.cached_tokens},
            "output_tokens": self.output_tokens,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": self.input_tokens + self.output_tokens,
        }

    def _require_active(self) -> None:
        if not self.started:
            raise CodexGlmAdapterError("Anthropic stream omitted message_start")
        if self.completed:
            raise CodexGlmAdapterError("Anthropic event arrived after message_stop")

    def feed(self, event: dict[str, Any]) -> bytes:
        if not isinstance(event, dict):
            raise CodexGlmAdapterError("Invalid Anthropic SSE event")
        event_type = event.get("type")
        if event_type == "ping":
            return b""
        if event_type == "error":
            error = event.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            raise CodexGlmAdapterError(
                message if isinstance(message, str) else "Apex GLM stream failed"
            )
        if event_type == "message_start":
            return self._message_start(event)

        self._require_active()
        if event_type == "content_block_start":
            events = self._content_block_start(event)
        elif event_type == "content_block_delta":
            events = self._content_block_delta(event)
        elif event_type == "content_block_stop":
            events = self._content_block_stop(event)
        elif event_type == "message_delta":
            events = self._message_delta(event)
        elif event_type == "message_stop":
            events = self._message_stop()
        else:
            raise CodexGlmAdapterError("Unsupported Anthropic SSE event")
        return _sse(events) if events else b""

    def _message_start(self, event: dict[str, Any]) -> bytes:
        if self.started:
            raise CodexGlmAdapterError("Duplicate Anthropic message_start")
        message = event.get("message")
        if not isinstance(message, dict):
            raise CodexGlmAdapterError("Invalid Anthropic message_start")
        response_id = message.get("id")
        model = message.get("model")
        content = message.get("content", [])
        if not isinstance(response_id, str) or not response_id:
            raise CodexGlmAdapterError("Invalid Apex response id")
        if not isinstance(model, str) or not model.lower().startswith("glm-"):
            raise CodexGlmAdapterError("Invalid Apex response model")
        if not isinstance(content, list) or content:
            raise CodexGlmAdapterError("Streaming message_start content must be empty")
        usage = message.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise CodexGlmAdapterError("Invalid Anthropic message_start usage")
        usage = usage or {}
        self.input_tokens = self._token_count(
            usage.get("input_tokens"), field="input token usage"
        )
        self.cached_tokens = self._token_count(
            usage.get("cache_read_input_tokens"), field="cached token usage"
        )
        self.response_id = response_id
        self.model = model
        self.started = True
        events = [
            self._emit(
                "response.created",
                response=_response_shell(
                    response_id, model, status="in_progress", output=[], usage=None,
                ),
            ),
            self._emit(
                "response.in_progress",
                response=_response_shell(
                    response_id, model, status="in_progress", output=[], usage=None,
                ),
            ),
        ]
        return _sse(events)

    @staticmethod
    def _block_index(event: dict[str, Any]) -> int:
        index = event.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise CodexGlmAdapterError("Invalid Anthropic content block index")
        return index

    def _content_block_start(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        index = self._block_index(event)
        if index in self.blocks:
            raise CodexGlmAdapterError("Duplicate Anthropic content block")
        block = event.get("content_block")
        if not isinstance(block, dict):
            raise CodexGlmAdapterError("Invalid Anthropic content block")
        block_type = block.get("type")
        if block_type in {"thinking", "redacted_thinking"}:
            self.blocks[index] = {"kind": "ignored"}
            return []

        output_index = len(self.output)
        if block_type == "text":
            initial_text = _bounded_text(
                block.get("text", ""), field="Apex response text"
            )
            item_id = f"msg_{self.response_id}_{output_index}"
            initial = {
                "id": item_id,
                "type": "message",
                "status": "in_progress",
                "role": "assistant",
                "content": [],
            }
            self.blocks[index] = {
                "kind": "text",
                "output_index": output_index,
                "item_id": item_id,
                "initial": initial,
                "text": initial_text,
            }
            events = [
                self._emit(
                    "response.output_item.added",
                    output_index=output_index,
                    item=initial,
                ),
                self._emit(
                    "response.content_part.added",
                    item_id=item_id,
                    output_index=output_index,
                    content_index=0,
                    part={"type": "output_text", "annotations": [], "text": ""},
                ),
            ]
            if initial_text:
                events.append(self._emit(
                    "response.output_text.delta",
                    item_id=item_id,
                    output_index=output_index,
                    content_index=0,
                    delta=initial_text,
                    logprobs=[],
                ))
            return events

        if block_type != "tool_use":
            raise CodexGlmAdapterError("Unsupported Apex content block")
        call_id = block.get("id")
        name = block.get("name")
        initial_input = block.get("input", {})
        if (
            not isinstance(call_id, str)
            or not call_id
            or not isinstance(name, str)
            or name not in self.tool_kinds
            or not isinstance(initial_input, dict)
        ):
            raise CodexGlmAdapterError("Invalid Apex tool_use block")
        route = self.tool_kinds[name]
        kind = route.get("kind") if isinstance(route, dict) else route
        output_name = route.get("name") if isinstance(route, dict) else name
        if kind == "custom":
            initial = {
                "id": call_id,
                "type": "custom_tool_call",
                "status": "in_progress",
                "call_id": call_id,
                "name": output_name,
                "input": "",
            }
        elif kind == "function":
            initial = {
                "id": call_id,
                "type": "function_call",
                "status": "in_progress",
                "call_id": call_id,
                "name": output_name,
                "arguments": "",
            }
            if isinstance(route, dict) and route.get("namespace"):
                initial["namespace"] = route["namespace"]
        else:
            raise CodexGlmAdapterError("Invalid Apex tool route")
        self.blocks[index] = {
            "kind": kind,
            "output_index": output_index,
            "call_id": call_id,
            "name": output_name,
            "initial": initial,
            "initial_input": initial_input,
            "json": "",
        }
        return [self._emit(
            "response.output_item.added",
            output_index=output_index,
            item=initial,
        )]

    def _content_block_delta(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        index = self._block_index(event)
        state = self.blocks.get(index)
        if state is None:
            raise CodexGlmAdapterError("Anthropic delta preceded content block start")
        delta = event.get("delta")
        if not isinstance(delta, dict):
            raise CodexGlmAdapterError("Invalid Anthropic content delta")
        if state["kind"] == "ignored":
            return []
        if state["kind"] == "text":
            if delta.get("type") != "text_delta":
                raise CodexGlmAdapterError("Invalid Anthropic text delta")
            text = _bounded_text(delta.get("text"), field="Apex response text delta")
            combined = state["text"] + text
            _bounded_text(combined, field="Apex response text")
            state["text"] = combined
            if not text:
                return []
            return [self._emit(
                "response.output_text.delta",
                item_id=state["item_id"],
                output_index=state["output_index"],
                content_index=0,
                delta=text,
                logprobs=[],
            )]
        if delta.get("type") != "input_json_delta":
            raise CodexGlmAdapterError("Invalid Anthropic tool input delta")
        partial = _bounded_text(
            delta.get("partial_json"), field="Apex tool input delta"
        )
        combined = state["json"] + partial
        _bounded_text(combined, field="Apex tool input")
        state["json"] = combined
        if state["kind"] != "function" or not partial:
            return []
        return [self._emit(
            "response.function_call_arguments.delta",
            item_id=state["call_id"],
            output_index=state["output_index"],
            delta=partial,
        )]

    def _content_block_stop(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        index = self._block_index(event)
        state = self.blocks.pop(index, None)
        if state is None:
            raise CodexGlmAdapterError("Anthropic block stop preceded block start")
        if state["kind"] == "ignored":
            return []
        output_index = state["output_index"]
        if state["kind"] == "text":
            text = state["text"]
            done_part = {"type": "output_text", "annotations": [], "text": text}
            final_item = {
                **state["initial"],
                "status": "completed",
                "content": [done_part],
            }
            self.output.append(final_item)
            return [
                self._emit(
                    "response.output_text.done",
                    item_id=state["item_id"],
                    output_index=output_index,
                    content_index=0,
                    text=text,
                    logprobs=[],
                ),
                self._emit(
                    "response.content_part.done",
                    item_id=state["item_id"],
                    output_index=output_index,
                    content_index=0,
                    part=done_part,
                ),
                self._emit(
                    "response.output_item.done",
                    output_index=output_index,
                    item=final_item,
                ),
            ]

        raw_json = state["json"]
        if raw_json:
            try:
                tool_input = json.loads(raw_json)
            except json.JSONDecodeError as exc:
                raise CodexGlmAdapterError("Invalid streamed Apex tool input") from exc
        else:
            tool_input = state["initial_input"]
        if not isinstance(tool_input, dict):
            raise CodexGlmAdapterError("Apex tool input must be an object")
        if state["kind"] == "custom":
            unwrapped = tool_input.get("input")
            if not isinstance(unwrapped, str):
                unwrapped = _compact_json(tool_input)
            unwrapped = _bounded_text(unwrapped, field="custom tool input")
            events = [self._emit(
                "response.custom_tool_call_input.delta",
                item_id=state["call_id"],
                output_index=output_index,
                delta=unwrapped,
            )]
            events.append(self._emit(
                "response.custom_tool_call_input.done",
                item_id=state["call_id"],
                output_index=output_index,
                input=unwrapped,
            ))
            final_item = {
                **state["initial"],
                "status": "completed",
                "input": unwrapped,
            }
        else:
            arguments = raw_json or _compact_json(tool_input)
            events = []
            if not raw_json and arguments:
                events.append(self._emit(
                    "response.function_call_arguments.delta",
                    item_id=state["call_id"],
                    output_index=output_index,
                    delta=arguments,
                ))
            events.append(self._emit(
                "response.function_call_arguments.done",
                item_id=state["call_id"],
                output_index=output_index,
                name=state["name"],
                arguments=arguments,
            ))
            final_item = {
                **state["initial"],
                "status": "completed",
                "arguments": arguments,
            }
        events.append(self._emit(
            "response.output_item.done",
            output_index=output_index,
            item=final_item,
        ))
        self.output.append(final_item)
        return events

    def _message_delta(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        usage = event.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise CodexGlmAdapterError("Invalid Anthropic message_delta usage")
        usage = usage or {}
        if "input_tokens" in usage:
            self.input_tokens = self._token_count(
                usage.get("input_tokens"), field="input token usage"
            )
        if "cache_read_input_tokens" in usage:
            self.cached_tokens = self._token_count(
                usage.get("cache_read_input_tokens"), field="cached token usage"
            )
        if "output_tokens" in usage:
            self.output_tokens = self._token_count(
                usage.get("output_tokens"), field="output token usage"
            )
        return []

    def _message_stop(self) -> list[dict[str, Any]]:
        if self.blocks:
            raise CodexGlmAdapterError("Anthropic message_stop preceded block stop")
        self.completed = True
        return [self._emit(
            "response.completed",
            response=_response_shell(
                self.response_id,
                self.model,
                status="completed",
                output=self.output,
                usage=self._usage(),
            ),
        )]

    def finish(self) -> None:
        if not self.completed:
            raise CodexGlmAdapterError("Anthropic stream ended before message_stop")


def anthropic_message_to_responses_sse(
    message: dict[str, Any],
    *,
    tool_kinds: dict[str, Any],
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
            route = tool_kinds[name]
            kind = route.get("kind") if isinstance(route, dict) else route
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
                output_name = (
                    route.get("name") if isinstance(route, dict) else name
                )
                initial = {
                    "id": call_id,
                    "type": "function_call",
                    "status": "in_progress",
                    "call_id": call_id,
                    "name": output_name,
                    "arguments": "",
                }
                if isinstance(route, dict) and route.get("namespace"):
                    initial["namespace"] = route["namespace"]
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
                    name=output_name,
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
