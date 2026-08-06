import asyncio
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .adapter.inbound.http.app import create_app


async def run_scheduler() -> None:
    """Run jobs in the dedicated scheduler process, never in an API worker."""
    app = create_app()
    async with app.router.lifespan_context(app):
        scheduler = AsyncIOScheduler(timezone=app.state.settings.timezone)

        async def sync_all() -> None:
            for source in app.state.sync.adapters:
                await app.state.sync.sync(source, app.state.settings.default_profile)

        fields = ("minute", "hour", "day", "month", "day_of_week")
        values = app.state.settings.sync_cron.split()
        if len(values) != 5:
            raise ValueError("SYNC_CRON must have five cron fields")
        scheduler.add_job(sync_all, "cron", **dict(zip(fields, values, strict=True)))
        scheduler.start()
        await asyncio.Event().wait()


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "scheduler":
    asyncio.run(run_scheduler())
