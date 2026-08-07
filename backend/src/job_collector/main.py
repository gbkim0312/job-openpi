import asyncio
import sys
from datetime import UTC, datetime

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
            profile_ids = list(app.state.profiles.items)
            if not profile_ids:
                return
            # Crawl one profile at a time.  Combining every profile into one
            # source request creates large bursts and can trigger upstream
            # throttling; sequential runs also make progress visible per profile.
            for source in app.state.sync.adapters:
                started_at = datetime.now(UTC)
                for profile_id in profile_ids:
                    await app.state.sync.sync(source, profile_id, mark_missing=False)
                await app.state.sync.reconcile_missing(source, started_at)

        async def recheck_all() -> None:
            # A source refresh confirms current records; expired missing postings
            # become CLOSED while undated/future-deadline records retain status.
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
