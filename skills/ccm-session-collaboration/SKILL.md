---
name: ccm-session-collaboration
description: >
  Reliably inspect and communicate with existing CCM tasks when the user
  mentions another session, a #task number, a task title, or asks one CCM
  session to read, compare, tell, or ask another session.
metadata:
  ccm:
    always: true
    priority: 10
    version: 1
    tags: [ccm, session, task, collaboration]
    tools: [ccm_list_tasks, ccm_read_task, ccm_send_task_message]
---

## CCM cross-session rules

CCM tasks are existing conversations. They are not Codex Sub-Agents. When the
user refers to `#48`, “another session”, or a task title, use the CCM task tools;
do not create a Sub-Agent, fork, or new session as a substitute.

### Required workflow

1. Resolve the target with `ccm_list_tasks`. A `#N` reference means CCM task id
   `N`; a title must be matched from the returned task list. Do not guess native
   Codex thread ids.
2. For requests to inspect, diagnose, summarize, compare, or continue based on
   another task, call `ccm_read_task` before relying on that task. Start with
   normal messages; use `include_tool_events=true` only when tool-level evidence
   is needed. Page backward with `before_id` when deeper history is required.
3. Reading is read-only. Call `ccm_send_task_message` only when the user
   explicitly asks to tell, ask, instruct, or send something to the target.
4. Before sending, make the message self-contained: identify the source task,
   state the requested action and constraints, and specify what response is
   needed. Do not forward secrets or large raw tool outputs.
5. Report delivery only when the tool says it was accepted. If resolution is
   ambiguous, show the candidates and ask the user which task they mean.

### Tool choice

| User intent | Tool sequence |
|---|---|
| “看看 #48 怎么了” | `ccm_list_tasks` → `ccm_read_task` |
| “比较 #48 和 #51” | list once → read both tasks |
| “告诉 #48 重跑测试” | list/resolve → optionally read for context → `ccm_send_task_message` |
| “开个子 agent 调研” | Use CCM Sub-Agent tools, not these task tools |

Always distinguish the CCM task id from the provider's native `session_id` or
thread id in your answer.
