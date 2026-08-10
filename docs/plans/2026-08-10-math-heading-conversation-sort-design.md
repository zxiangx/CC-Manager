# Formula heading recovery and conversation-time sorting

## Scope

Two narrow changes are required:

1. Recover display math when a model accidentally prefixes the opening display
   delimiter with an ATX heading marker, for example `# \\[` or `### $$`.
2. In automatic task ordering mode, sort logical conversations by their latest
   real user/assistant message rather than by the time somebody opened the chat.

## Markdown design

`MarkdownRenderer` normalizes only lines whose entire meaningful suffix starts
with a display-math delimiter. It removes one leading ATX marker before the
Markdown parser runs. The scanner tracks fenced code blocks, so examples inside
code remain literal. Ordinary headings, including headings containing inline
math and prose, remain headings. Existing AST-based backslash-math parsing and
KaTeX safety settings remain unchanged.

## Sorting design

`TaskQueue.list_tasks` computes a correlated latest-conversation timestamp from
non-empty `message` log entries with role `user` or `assistant`. For a canonical
Task, logs from all implementation-only edited-message Tasks rooted at it count
toward the same logical conversation. Creation time is the fallback when a Task
has no conversation log.

When automatic sorting is enabled, this timestamp is authoritative within each
starred/non-starred group and explicit `sort_order` values are ignored. When
automatic sorting is disabled, the existing manual `sort_order`/creation-time
behavior remains available. The setting label changes from access-based wording
to conversation-time wording.

## Verification

- Renderer tests cover `# \\[` and `### $$`, genuine headings, and fenced code.
- Queue tests cover latest-message ordering, ignored access timestamps, logical
  branch aggregation, creation fallback, starred pinning, and manual mode.
- Run the focused frontend/backend suites, then the frontend production build.
