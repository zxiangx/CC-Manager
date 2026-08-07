# Monitor Feature Switch Design

## Goal

Add one persisted administrator switch for CCM Monitor. The switch defaults to
off. While it is off, Codex must not receive Monitor skill instructions or the
Monitor MCP tools, and Monitor creation must fail closed at the API boundary.
Turning it off also terminates CCM-owned Codex Monitor sessions that are still
running. The existing Claude Monitor path is unaffected.

## Behaviour

- Store `codex_monitor_enabled` in the singleton `global_settings` row.
- The effective default is `false`, including upgrades from an older database.
- The existing `CODEX_MAIN_MCP_ENABLED` setting remains the emergency gate for
  the whole main-task MCP server. Monitor is usable only when both gates and
  the existing task-scope checks pass.
- A task may keep its persisted `enabled_skills.monitor` preference while the
  global switch is off. This preserves the user's per-task choice if the
  feature is enabled again, but the preference has no runtime effect while
  disabled.
- Disabling transitions every local Codex CCM Monitor in `running` state to
  `cancelled`, clears its scheduling/turn ownership fields, stops its runtime
  process, removes generated MCP configuration, and broadcasts the terminal
  state.
- Enabling affects the next Codex turn. The task prompt and main-task MCP tool
  list are rebuilt for every launch, so no backend restart is required.

## Boundaries

This switch controls the custom CCM Monitor exposed to Codex. It does not turn
off Codex's native automations, scheduled wakeups, goals, or sub-agents.
Existing restrictions for Worker-managed, shared, and PR-review tasks remain
unchanged.

## Verification

- Runtime settings default to off and round-trip the persisted value.
- Codex task context omits the Monitor skill while off and includes it while on.
- Main-task MCP specs omit all three Monitor controller tools while off.
- Monitor creation is rejected while off.
- Disabling cancels and cleans up existing running Monitor sessions.
- The administrator menu renders and updates the switch, including the warning
  shown before disabling.
