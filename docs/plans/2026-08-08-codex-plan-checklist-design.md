# Codex 动态 Plan 清单设计

## 目标

CCM 聊天展示 Codex `update_plan` 的完整清单快照，清楚区分待办、进行中和已完成。同一 Codex turn 只显示一张持续更新的卡片，刷新页面后仍看到最新快照，不与项目 Todo 或原生 Goal 状态混用。

## 协议与数据流

Codex app-server 当前生成的 v2 协议以 `turn/plan/updated` 发布权威快照：`threadId`、`turnId`、可选 `explanation` 和 `plan: [{step,status}]`。adapter 把它规范化成内部 `todo_list` 事件，并以 `todo:<turnId>` 作为稳定 `todo_id`。旧 `codex exec --json` 的 `item.updated/item.completed + todo_list` 继续走兼容解析。

状态统一为 `pending`、`in_progress`、`completed`。后端为同一 Task retry generation 和 `todo_id` 删除旧 snapshot、插入最新 snapshot；重新插入可让计划留在按 log id 获取的最新历史页。WebSocket 实时广播与 HTTP 历史同时返回 `todo_id`、`todo_explanation` 和 `todo_items`。前端按 `todo_id` 替换既有消息，渲染单张 Plan 卡片及完成计数。

## 边界与验证

缺少文本的 step 被忽略，未知状态降级为 pending；没有 turn id 的 exec 兼容事件回退到 native item id。计划更新不改变 Task/Goal 状态、未读标记或 Fork 边界。测试覆盖正式协议转换、旧格式状态规范化、durable snapshot 替换、HTTP 结构化输出、首次渲染和连续 WebSocket 更新，并执行完整 Chat 测试、TypeScript 检查和 production build。
