import asyncio
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .adapter.inbound.http.app import create_app
from .runtime_settings import load_schedule_settings


async def run_scheduler() -> None:
    """Run jobs in the dedicated scheduler process, never in an API worker."""
    app = create_app()
    async with app.router.lifespan_context(app):
        scheduler = AsyncIOScheduler(timezone=app.state.settings.timezone)

        async def sync_all() -> None:
            for source in app.state.sync.adapters:
                await app.state.sync.sync(source, app.state.settings.default_profile)

        async def recheck_all() -> None:
            # A source refresh confirms current records and turns postings absent
            # from its completed search into UNKNOWN, never directly CLOSED.
            await sync_all()

        active_schedule: tuple[str, str] | None = None

        async def refresh_schedule() -> None:
            nonlocal active_schedule
            async with app.state.sessions() as session:
                settings = await load_schedule_settings(session)
            requested = (settings.sync_cron, settings.recheck_cron)
            if requested == active_schedule:
                return
            scheduler.add_job(
                sync_all,
                CronTrigger.from_crontab(settings.sync_cron, timezone=app.state.settings.timezone),
                id="profile-sync",
                replace_existing=True,
                coalesce=True,
            )
            scheduler.add_job(
                recheck_all,
                CronTrigger.from_crontab(
                    settings.recheck_cron, timezone=app.state.settings.timezone
                ),
                id="active-recheck",
                replace_existing=True,
                coalesce=True,
            )
            active_schedule = requested

        scheduler.start()
        await refresh_schedule()
        scheduler.add_job(refresh_schedule, "interval", seconds=30, id="schedule-refresh")
        await asyncio.Event().wait()


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "scheduler":
    asyncio.run(run_scheduler())
