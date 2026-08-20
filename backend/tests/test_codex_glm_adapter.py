import json

import pytest

from backend.services.codex_glm_adapter import (
    AnthropicMessagesStreamAdapter,
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


def _stream_message_start():
    return {
        "type": "message_start",
        "message": {
            "id": "msg-stream",
            "model": "glm-5.3",
            "content": [],
            # Apex sends placeholders here and the authoritative counts in
            # the terminal message_delta.
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    }


def test_streams_text_deltas_before_message_completion():
    adapter = AnthropicMessagesStreamAdapter(tool_kinds={})

    created = _events(adapter.feed(_stream_message_start()))
    started = _events(adapter.feed({
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    }))
    first_delta = _events(adapter.feed({
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "GLM "},
    }))

    assert [event["type"] for event in created] == [
        "response.created",
        "response.in_progress",
    ]
    assert started[0]["type"] == "response.output_item.added"
    assert first_delta[0]["type"] == "response.output_text.delta"
    assert first_delta[0]["delta"] == "GLM "
    assert adapter.completed is False

    adapter.feed({
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "ready"},
    })
    done = _events(adapter.feed({"type": "content_block_stop", "index": 0}))
    adapter.feed({
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn"},
        "usage": {
            "input_tokens": 11,
            "output_tokens": 2,
            "cache_read_input_tokens": 3,
        },
    })
    completed = _events(adapter.feed({"type": "message_stop"}))
    adapter.finish()

    assert done[0]["type"] == "response.output_text.done"
    assert done[0]["text"] == "GLM ready"
    assert completed[-1]["type"] == "response.completed"
    response = completed[-1]["response"]
    assert response["output"][0]["content"][0]["text"] == "GLM ready"
    assert response["usage"] == {
        # Anthropic reports uncached input and cache reads separately, while
        # Responses reports cached tokens as a subset of total input.
        "input_tokens": 14,
        "input_tokens_details": {"cached_tokens": 3},
        "output_tokens": 2,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 16,
    }


def test_streams_function_arguments_and_safely_unwraps_custom_input():
    adapter = AnthropicMessagesStreamAdapter(tool_kinds={
        "read_file": "function",
        "apply_patch": "custom",
    })
    adapter.feed(_stream_message_start())
    function_start = _events(adapter.feed({
        "type": "content_block_start",
        "index": 0,
        "content_block": {
            "type": "tool_use",
            "id": "call-fn",
            "name": "read_file",
            "input": {},
        },
    }))
    function_delta = _events(adapter.feed({
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": '{"path":'},
    }))
    adapter.feed({
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": '"README.md"}'},
    })
    function_done = _events(adapter.feed({
        "type": "content_block_stop",
        "index": 0,
    }))

    assert function_start[0]["type"] == "response.output_item.added"
    assert function_delta[0]["type"] == "response.function_call_arguments.delta"
    assert function_delta[0]["delta"] == '{"path":'
    assert function_done[-1]["item"]["arguments"] == '{"path":"README.md"}'

    adapter.feed({
        "type": "content_block_start",
        "index": 1,
        "content_block": {
            "type": "tool_use",
            "id": "call-custom",
            "name": "apply_patch",
            "input": {},
        },
    })
    assert adapter.feed({
        "type": "content_block_delta",
        "index": 1,
        "delta": {"type": "input_json_delta", "partial_json": '{"input":"*** '},
    }) == b""
    adapter.feed({
        "type": "content_block_delta",
        "index": 1,
        "delta": {"type": "input_json_delta", "partial_json": 'Patch\\n"}'},
    })
    custom_done = _events(adapter.feed({
        "type": "content_block_stop",
        "index": 1,
    }))

    assert custom_done[0]["type"] == "response.custom_tool_call_input.delta"
    assert custom_done[0]["delta"] == "*** Patch\n"
    assert custom_done[-1]["item"]["input"] == "*** Patch\n"


def test_stream_adapter_rejects_invalid_order_and_incomplete_eof():
    adapter = AnthropicMessagesStreamAdapter(tool_kinds={})
    with pytest.raises(CodexGlmAdapterError, match="message_start"):
        adapter.feed({"type": "message_stop"})

    adapter.feed(_stream_message_start())
    with pytest.raises(CodexGlmAdapterError, match="before message_stop"):
        adapter.finish()


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
    assert payload["stream"] is True
    assert payload["max_tokens"] == 32_768
    assert payload["tools"][0]["input_schema"]["required"] == ["path"]
    assert payload["tools"][1]["input_schema"]["required"] == ["input"]
    assert tool_kinds == {"read_file": "function", "apply_patch": "custom"}


def test_omits_openai_hosted_web_search_but_keeps_local_tools():
    payload, tool_kinds = responses_request_to_anthropic(_request(tools=[
        {"type": "web_search", "external_web_access": True},
        {
            "type": "function",
            "name": "exec_command",
            "description": "Run a command",
            "parameters": {"type": "object", "properties": {}},
        },
    ]))

    assert [tool["name"] for tool in payload["tools"]] == ["exec_command"]
    assert tool_kinds == {"exec_command": "function"}


def test_flattens_namespace_tools_and_restores_namespace_on_response():
    payload, tool_kinds = responses_request_to_anthropic(_request(tools=[{
        "type": "namespace",
        "name": "mcp__ccm_skills",
        "description": "CCM task tools",
        "tools": [{
            "type": "function",
            "name": "ccm_command_help",
            "description": "Read command help",
            "parameters": {"type": "object", "properties": {}},
            "strict": False,
        }],
    }]))

    upstream_name = "mcp__ccm_skills__ccm_command_help"
    assert payload["tools"][0]["name"] == upstream_name
    assert tool_kinds[upstream_name] == {
        "kind": "function",
        "namespace": "mcp__ccm_skills",
        "name": "ccm_command_help",
    }

    response = anthropic_message_to_responses_sse({
        "id": "msg-namespace",
        "model": "glm-5.3",
        "stop_reason": "tool_use",
        "content": [{
            "type": "tool_use",
            "id": "call-namespace",
            "name": upstream_name,
            "input": {},
        }],
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }, tool_kinds=tool_kinds)
    item = _events(response)[-1]["response"]["output"][0]

    assert item["type"] == "function_call"
    assert item["name"] == "ccm_command_help"
    assert item["namespace"] == "mcp__ccm_skills"


def test_replays_namespace_tool_call_and_result():
    payload, _ = responses_request_to_anthropic(_request(
        tools=[{
            "type": "namespace",
            "name": "mcp__ccm_skills",
            "description": "CCM task tools",
            "tools": [{
                "type": "function",
                "name": "ccm_command_help",
                "parameters": {"type": "object", "properties": {}},
            }],
        }],
        input_items=[
            {"type": "message", "role": "user", "content": "Help"},
            {
                "type": "function_call",
                "namespace": "mcp__ccm_skills",
                "name": "ccm_command_help",
                "call_id": "call-1",
                "arguments": "{}",
            },
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "Available commands",
            },
        ],
    ))

    assert payload["messages"][1]["content"][0]["name"] == (
        "mcp__ccm_skills__ccm_command_help"
    )
    assert payload["messages"][2]["content"][0]["tool_use_id"] == "call-1"


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
        "usage": {
            "input_tokens": 10,
            "cache_read_input_tokens": 3,
            "output_tokens": 4,
        },
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
    assert completed["response"]["usage"] == {
        "input_tokens": 13,
        "input_tokens_details": {"cached_tokens": 3},
        "output_tokens": 4,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 17,
    }


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
