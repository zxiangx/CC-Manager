import json

import pytest

from backend.services.codex_glm_adapter import (
    CodexGlmAdapterError,
    anthropic_message_to_responses_sse,
    responses_request_to_anthropic,
)


def _request(*, input_items=None, tools=None):
    return {
        "model": "glm-5.3",
        "instructions": "Work carefully.",
        "input": input_items or [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Inspect repo"}],
            },
        ],
        "tools": tools or [],
        "stream": True,
    }


def _events(payload: bytes) -> list[dict]:
    result = []
    for block in payload.decode().strip().split("\n\n"):
        data = next(
            line[6:] for line in block.splitlines() if line.startswith("data: ")
        )
        result.append(json.loads(data))
    return result


def test_converts_instructions_messages_and_function_custom_tools():
    payload, tool_kinds = responses_request_to_anthropic(_request(tools=[
        {
            "type": "function",
            "name": "read_file",
            "description": "Read one file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        {
            "type": "custom",
            "name": "apply_patch",
            "description": "Apply a patch",
            "format": {"type": "text"},
        },
    ]))

    assert payload["model"] == "glm-5.3"
    assert payload["system"] == "Work carefully."
    assert payload["messages"] == [{
        "role": "user",
        "content": [{"type": "text", "text": "Inspect repo"}],
    }]
    assert payload["stream"] is False
    assert payload["max_tokens"] == 32_768
    assert payload["tools"][0]["input_schema"]["required"] == ["path"]
    assert payload["tools"][1]["input_schema"]["required"] == ["input"]
    assert tool_kinds == {"read_file": "function", "apply_patch": "custom"}


def test_reconstructs_prior_tool_call_and_result_for_next_turn():
    payload, tool_kinds = responses_request_to_anthropic(_request(
        tools=[{
            "type": "custom",
            "name": "exec_command",
            "description": "Run shell input",
            "format": {"type": "text"},
        }],
        input_items=[
            {"type": "message", "role": "user", "content": "Run pwd"},
            {
                "type": "custom_tool_call",
                "call_id": "call-1",
                "name": "exec_command",
                "input": "pwd",
            },
            {
                "type": "custom_tool_call_output",
                "call_id": "call-1",
                "output": "/workspace",
            },
        ],
    ))

    assert tool_kinds == {"exec_command": "custom"}
    assert payload["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "Run pwd"}]},
        {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": "call-1",
                "name": "exec_command",
                "input": {"input": "pwd"},
            }],
        },
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "call-1",
                "content": "/workspace",
            }],
        },
    ]


def test_rejects_unbounded_or_unknown_request_shapes():
    with pytest.raises(CodexGlmAdapterError, match="model"):
        responses_request_to_anthropic({"model": "gpt-5.4", "input": []})
    with pytest.raises(CodexGlmAdapterError, match="input item"):
        responses_request_to_anthropic(_request(input_items=[
            {"type": "computer_call", "id": "unsafe"},
        ]))


def test_converts_text_message_to_complete_responses_sse():
    payload = anthropic_message_to_responses_sse({
        "id": "msg-1",
        "model": "glm-5.3",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "Done."}],
        "usage": {"input_tokens": 10, "output_tokens": 4},
    }, tool_kinds={})
    events = _events(payload)

    assert events[0]["type"] == "response.created"
    assert any(
        event["type"] == "response.output_text.delta"
        and event["delta"] == "Done."
        for event in events
    )
    completed = events[-1]
    assert completed["type"] == "response.completed"
    assert completed["response"]["status"] == "completed"
    assert completed["response"]["output"][0]["content"][0]["text"] == "Done."
    assert completed["response"]["usage"]["total_tokens"] == 14


def test_converts_function_and_custom_tool_use_blocks():
    payload = anthropic_message_to_responses_sse({
        "id": "msg-tools",
        "model": "glm-5.3",
        "stop_reason": "tool_use",
        "content": [
            {
                "type": "tool_use",
                "id": "call-fn",
                "name": "read_file",
                "input": {"path": "README.md"},
            },
            {
                "type": "tool_use",
                "id": "call-custom",
                "name": "apply_patch",
                "input": {"input": "*** Begin Patch"},
            },
        ],
        "usage": {"input_tokens": 20, "output_tokens": 8},
    }, tool_kinds={"read_file": "function", "apply_patch": "custom"})
    completed = _events(payload)[-1]["response"]

    assert completed["output"][0] == {
        "id": "call-fn",
        "type": "function_call",
        "status": "completed",
        "call_id": "call-fn",
        "name": "read_file",
        "arguments": '{"path":"README.md"}',
    }
    assert completed["output"][1] == {
        "id": "call-custom",
        "type": "custom_tool_call",
        "status": "completed",
        "call_id": "call-custom",
        "name": "apply_patch",
        "input": "*** Begin Patch",
    }
