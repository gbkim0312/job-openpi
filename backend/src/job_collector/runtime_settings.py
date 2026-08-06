from dataclasses import dataclass

from sqlalchemy import select

from .persistence import RuntimeSettingRow


@dataclass(frozen=True)
class ScheduleSettings:
    sync_cron: str
    recheck_cron: str


@dataclass(frozen=True)
class RequestPacingSettings:
    random_delay_enabled: bool
    random_delay_max_seconds: float


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


async def seed_request_pacing_settings(
    session, random_delay_enabled: bool, random_delay_max_seconds: float
) -> None:
    values = {
        "request_random_delay_enabled": "true" if random_delay_enabled else "false",
        "request_random_delay_max_seconds": str(random_delay_max_seconds),
    }
    for key, value in values.items():
        if await session.get(RuntimeSettingRow, key) is None:
            session.add(RuntimeSettingRow(key=key, value=value))
    await session.commit()


async def load_request_pacing_settings(session) -> RequestPacingSettings:
    rows = (await session.execute(select(RuntimeSettingRow))).scalars()
    values = {row.key: row.value for row in rows}
    return RequestPacingSettings(
        random_delay_enabled=values.get("request_random_delay_enabled", "false").lower() == "true",
        random_delay_max_seconds=float(values.get("request_random_delay_max_seconds", "0.5")),
    )


async def save_request_pacing_settings(session, settings: RequestPacingSettings) -> None:
    values = {
        "request_random_delay_enabled": "true" if settings.random_delay_enabled else "false",
        "request_random_delay_max_seconds": str(settings.random_delay_max_seconds),
    }
    for key, value in values.items():
        row = await session.get(RuntimeSettingRow, key)
        if row is None:
            session.add(RuntimeSettingRow(key=key, value=value))
        else:
            row.value = value
    await session.commit()
