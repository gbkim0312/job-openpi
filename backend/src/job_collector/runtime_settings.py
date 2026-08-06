from dataclasses import dataclass

from sqlalchemy import select

from .persistence import RuntimeSettingRow


@dataclass(frozen=True)
class ScheduleSettings:
    sync_cron: str
    recheck_cron: str


async def seed_schedule_settings(session, sync_cron: str, recheck_cron: str) -> None:
    for key, value in {"sync_cron": sync_cron, "recheck_cron": recheck_cron}.items():
        if await session.get(RuntimeSettingRow, key) is None:
            session.add(RuntimeSettingRow(key=key, value=value))
    await session.commit()


async def load_schedule_settings(session) -> ScheduleSettings:
    rows = (await session.execute(select(RuntimeSettingRow))).scalars()
    values = {row.key: row.value for row in rows}
    return ScheduleSettings(sync_cron=values["sync_cron"], recheck_cron=values["recheck_cron"])


async def save_schedule_settings(session, settings: ScheduleSettings) -> None:
    for key, value in {
        "sync_cron": settings.sync_cron,
        "recheck_cron": settings.recheck_cron,
    }.items():
        row = await session.get(RuntimeSettingRow, key)
        if row is None:
            session.add(RuntimeSettingRow(key=key, value=value))
        else:
            row.value = value
    await session.commit()
