import pytest

from backend.models.instance import Instance
from backend.models.log_entry import LogEntry
from backend.models.task import Task
from backend.services.instance_manager import InstanceManager


@pytest.mark.asyncio
async def test_request_blocked_summary_includes_all_results_since_last_message(db_factory):
    async with db_factory() as db:
        instance = Instance(name="blocked-summary")
        task = Task(title="blocked", provider="codex", status="failed")
        db.add_all([instance, task])
        await db.flush()
        db.add_all([
            LogEntry(
                instance_id=instance.id, task_id=task.id,
                event_type="message", role="assistant", content="earlier",
            ),
            LogEntry(
                instance_id=instance.id, task_id=task.id,
                event_type="tool_result", role="tool", tool_output="one",
            ),
            LogEntry(
                instance_id=instance.id, task_id=task.id,
                event_type="tool_use", role="assistant",
            ),
            LogEntry(
                instance_id=instance.id, task_id=task.id,
                event_type="tool_result", role="tool", tool_output="two",
            ),
            LogEntry(
                instance_id=instance.id, task_id=task.id,
                event_type="tool_use", role="assistant",
            ),
            LogEntry(
                instance_id=instance.id, task_id=task.id,
                event_type="tool_result", role="tool", tool_output="three",
            ),
        ])
        await db.commit()
        task_id = task.id

    manager = InstanceManager(db_factory, None)
    selected = []

    async def summarize(rows):
        selected.extend(rows)
        return None

    manager._summarize_blocked_tool_outputs = summarize
    await manager._request_blocked_tool_summary(task_id)
    assert [row["tool_output"] for row in selected] == ["one", "two", "three"]


@pytest.mark.asyncio
async def test_request_blocked_summary_stops_after_user_or_assistant_message(db_factory):
    async with db_factory() as db:
        instance = Instance(name="blocked-summary-boundary")
        task = Task(title="blocked", provider="codex", status="failed")
        db.add_all([instance, task])
        await db.flush()
        stale = LogEntry(
            instance_id=instance.id, task_id=task.id,
            event_type="tool_result", role="tool", tool_output="stale",
        )
        db.add(stale)
        await db.flush()
        db.add(LogEntry(
            instance_id=instance.id, task_id=task.id,
            event_type="message", role="assistant", content="consumed",
        ))
        await db.flush()
        final = LogEntry(
            instance_id=instance.id, task_id=task.id,
            event_type="tool_result", role="tool", tool_output="final",
        )
        db.add(final)
        await db.commit()
        task_id = task.id

    manager = InstanceManager(db_factory, None)
    selected = []
    async def summarize(rows):
        selected.extend(rows)
        return None
    manager._summarize_blocked_tool_outputs = summarize
    await manager._request_blocked_tool_summary(task_id)
    assert [row["tool_output"] for row in selected] == ["final"]
