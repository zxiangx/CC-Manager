"""Global availability gate for CCM's custom Monitor feature."""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.global_settings import GlobalSettings


def effective_monitor_enabled(row: GlobalSettings | None) -> bool:
    """Return the fail-closed persisted Monitor setting."""

    return bool(row is not None and row.codex_monitor_enabled is True)


async def monitor_enabled(db: AsyncSession) -> bool:
    return effective_monitor_enabled(await db.get(GlobalSettings, 1))

