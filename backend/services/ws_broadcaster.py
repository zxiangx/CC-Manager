import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


_SEND_TIMEOUT = 5  # seconds — drop slow clients rather than blocking the pipeline


class WebSocketBroadcaster:
    """Central hub for broadcasting real-time events to WebSocket clients."""

    def __init__(self):
        self.subscriptions: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self.db_factory = None

    async def subscribe(self, ws: WebSocket, channels: list[str]):
        async with self._lock:
            for ch in channels:
                self.subscriptions[ch].add(ws)

    async def unsubscribe(self, ws: WebSocket):
        async with self._lock:
            for ch in list(self.subscriptions):
                self.subscriptions[ch].discard(ws)
                if not self.subscriptions[ch]:
                    del self.subscriptions[ch]

    async def _send_with_timeout(self, ws: WebSocket, message: str) -> bool:
        """Send text to a WebSocket with a timeout. Returns False on failure."""
        try:
            await asyncio.wait_for(ws.send_text(message), timeout=_SEND_TIMEOUT)
            return True
        except asyncio.TimeoutError:
            logger.warning("WebSocket send timed out after %ds, dropping client", _SEND_TIMEOUT)
            return False
        except Exception as e:
            logger.debug("WebSocket send failed: %s", e)
            return False

    async def _broadcast_snapshot(
        self,
        subscribers: list[WebSocket],
        message: str,
    ) -> None:
        """Send one snapshot concurrently and evict failed connections."""
        if not subscribers:
            return
        results = await asyncio.gather(*(
            self._send_with_timeout(ws, message)
            for ws in subscribers
        ))
        dead = [
            ws
            for ws, delivered in zip(subscribers, results)
            if not delivered
        ]
        for ws in dead:
            await self.unsubscribe(ws)

    async def broadcast(self, channel: str, data: dict):
        message = json.dumps({"channel": channel, "data": data})
        # 迭代必须用快照：send 是悬挂点，期间并发的 (un)subscribe 会修改活集合
        # → RuntimeError: Set changed size during iteration → API 500
        #（2026-07-16 前端 WS 连环 keepalive 超时断开时命中，create_monitor 被炸出重复 monitor）
        subs = list(self.subscriptions.get(channel, set()))
        await self._broadcast_snapshot(subs, message)

        # Mirror status_change to per-task channel so /ws/shared subscribers see it
        if channel == "tasks" and data.get("event") == "status_change" and data.get("task_id"):
            task_channel = f"task:{data['task_id']}"
            task_msg = json.dumps({"channel": task_channel, "data": data})
            await self._broadcast_snapshot(
                list(self.subscriptions.get(task_channel, set())),
                task_msg,
            )

        # Hidden edited-message Tasks execute independently, while the sidebar
        # keeps one canonical session row. Mirror live status/background events
        # to that row only when this hidden Task is the last selected branch.
        if (
            channel == "tasks"
            and data.get("event") in {"status_change", "background_activity"}
            and isinstance(data.get("task_id"), int)
            and callable(self.db_factory)
        ):
            root_id = await self._selected_message_branch_root(data["task_id"])
            if root_id is not None:
                root_data = {**data, "task_id": root_id}
                root_message = json.dumps({"channel": "tasks", "data": root_data})
                await self._broadcast_snapshot(
                    list(self.subscriptions.get("tasks", set())),
                    root_message,
                )
                root_channel = f"task:{root_id}"
                await self._broadcast_snapshot(
                    list(self.subscriptions.get(root_channel, set())),
                    json.dumps({"channel": root_channel, "data": root_data}),
                )

        # The global workers channel contains private IPs and bootstrap logs, so
        # members cannot subscribe to it. Mirror each event to an ACL-checked
        # worker-specific channel to preserve real-time logs for that owner.
        worker_id = data.get("worker_id")
        if (
            channel == "workers"
            and isinstance(worker_id, int)
            and not isinstance(worker_id, bool)
            and worker_id > 0
        ):
            worker_channel = f"worker:{worker_id}"
            worker_message = json.dumps({
                "channel": worker_channel,
                "data": data,
            })
            await self._broadcast_snapshot(
                list(self.subscriptions.get(worker_channel, set())),
                worker_message,
            )

        # Fire-and-forget share notifications on terminal status changes
        if (
            channel == "tasks"
            and data.get("event") == "status_change"
            and data.get("new_status") in ("completed", "failed", "cancelled")
            and data.get("background_active") is not True
            and self.db_factory
        ):
            asyncio.create_task(self._notify_shared_status(data))

    async def _selected_message_branch_root(self, task_id: int) -> int | None:
        try:
            from backend.models.task import Task

            async with self.db_factory() as db:
                task = await db.get(Task, task_id)
                if task is None or task.message_branch_root_task_id is None:
                    return None
                root = await db.get(Task, task.message_branch_root_task_id)
                if (
                    root is None
                    or root.active_message_branch_task_id != task.id
                ):
                    return None
                return root.id
        except Exception:
            logger.exception(
                "message branch status mirror failed for task %s",
                task_id,
            )
            return None

    async def _notify_shared_status(self, data: dict):
        try:
            from backend.services.share_notifier import notify_shared_users_on_status_change
            await notify_shared_users_on_status_change(
                self.db_factory, data["task_id"], data["new_status"],
            )
        except Exception:
            logger.debug("share status notification failed for task %s", data.get("task_id"))
