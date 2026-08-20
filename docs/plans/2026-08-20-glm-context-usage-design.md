# GLM Context Usage Correction Design

## Goal

Make CCM persist accurate per-request token usage and model context windows for Apex-hosted GLM turns.

## Design

Apex's Anthropic-compatible streaming endpoint reports placeholder usage in `message_start` and authoritative usage in the terminal `message_delta`. The stream adapter will therefore treat any usage fields present in `message_delta` as final replacements for input, cached-input, and output token counts. It will continue accepting providers that only populate `message_start` by retaining earlier values for fields omitted from the terminal event.

Codex app-server assigns a generic `modelContextWindow` to custom Responses-compatible models. That value is not a reliable GLM capability signal. When CCM persists context usage for a Codex task whose selected model begins with `glm-`, it will always replace the app-server window with `codex_context_window(model)`. Other Codex models keep the existing behavior, including using app-server/rollout values where authoritative and falling back to the static table only when absent.

Tests cover Apex's observed `message_start input_tokens=0` followed by terminal nonzero usage, and a GLM task receiving the generic 258,400 window while its configured capability is 204,800. This keeps UI meters and automatic compaction on the same corrected persisted value.
