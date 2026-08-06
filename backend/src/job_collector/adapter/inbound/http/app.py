from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ....bootstrap import Settings
from ....persistence import (
    Base,
    CrawlRunRow,
    JobPostingRow,
    JobSnapshotRow,
    SearchProfileRow,
    get_job,
    session_factory,
)
from ....profiles import ProfileStore, SearchProfile
from ....runtime_settings import (
    ScheduleSettings,
    load_schedule_settings,
    save_schedule_settings,
    seed_schedule_settings,
)
from ....sources import WantedJobSourceAdapter
from ....sync import SyncService


class SyncRequest(BaseModel):
    profile: str | None = None
    mode: str = "incremental"


class ScheduleRequest(BaseModel):
    sync_cron: str
    recheck_cron: str


def row_dict(row: JobPostingRow, detail: bool = False) -> dict:
    value = {
        "id": str(row.id),
        "source": row.source,
        "source_job_id": row.source_job_id,
        "company_name": row.company_name,
        "title": row.title,
        "effective_status": row.manual_status_override or row.detected_status,
        "detected_status": row.detected_status,
        "region": row.region,
        "location_raw": row.location_raw,
        "experience": {
            "raw": row.experience_raw,
            "min_years": row.min_experience_years,
            "max_years": row.max_experience_years,
        },
        "deadline": {
            "raw": row.deadline_raw,
            "date": row.deadline_date,
            "always_open": row.always_open,
        },
        "categories": row.categories,
        "skills": row.skills,
        "first_seen_at": row.first_seen_at,
        "last_checked_at": row.last_checked_at,
        "url": row.canonical_url,
    }
    if detail:
        value.update(
            {
                "source_status": row.source_status,
                "status_reason": row.status_reason,
                "city": row.city,
                "employment_type": row.employment_type,
                "posted_at": row.posted_at,
                "last_seen_at": row.last_seen_at,
                "closed_at": row.closed_at,
                "responsibilities": row.responsibilities,
                "requirements": row.requirements,
                "preferred_qualifications": row.preferred_qualifications,
            }
        )
    return value


def create_app() -> FastAPI:
    settings = Settings()
    sessions = session_factory(settings.database_url)
    profiles = ProfileStore(settings.profiles_dir)
    adapters = (
        {
            "WANTED": WantedJobSourceAdapter(
                settings.wanted_base_url,
                settings.http_timeout_seconds,
                settings.wanted_request_delay_seconds,
            )
        }
        if settings.wanted_enabled
        else {}
    )
    sync_service = SyncService(sessions, adapters, profiles)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # SQLite makes local development work; production uses migration service.
        if settings.database_url.startswith("sqlite"):
            async with sessions.kw["bind"].begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            await profiles.seed_and_load(session)
            await seed_schedule_settings(session, settings.sync_cron, settings.recheck_cron)
        app.state.settings, app.state.sessions, app.state.profiles, app.state.sync = (
            settings,
            sessions,
            profiles,
            sync_service,
        )
        yield

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[x.strip() for x in settings.cors_origins.split(",")],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def db():
        async with sessions() as session:
            yield session

    async def admin(request: Request):
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ") if auth.startswith("Bearer ") else ""
        if not token:
            raise HTTPException(401, "administrator authentication required")
        if not hmac.compare_digest(token, settings.admin_api_key):
            raise HTTPException(403, "invalid administrator credentials")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(session: AsyncSession = Depends(db)):
        try:
            await session.execute(select(1))
            return {"status": "ready", "profiles": len(profiles.items)}
        except SQLAlchemyError:
            raise HTTPException(503, "database unavailable")

    @app.get("/api/v1/jobs")
    async def jobs(
        session: AsyncSession = Depends(db),
        keyword: str | None = None,
        sources: str | None = None,
        statuses: str = "ACTIVE",
        categories: str | None = None,
        skills: str | None = None,
        region: str | None = None,
        min_experience: int | None = None,
        max_experience: int | None = None,
        limit: int = Query(20, ge=1, le=100),
        cursor: str | None = None,
        sort: str = "first_seen_at:desc",
    ):
        clauses = []
        if statuses:
            clauses.append(
                (
                    JobPostingRow.manual_status_override if False else JobPostingRow.detected_status
                ).in_(statuses.split(","))
            )
        if sources:
            clauses.append(JobPostingRow.source.in_(sources.split(",")))
        if region:
            clauses.append(JobPostingRow.region == region)
        if keyword:
            clauses.append(
                or_(
                    JobPostingRow.title.ilike(f"%{keyword}%"),
                    JobPostingRow.company_name.ilike(f"%{keyword}%"),
                )
            )
        if min_experience is not None:
            clauses.append(
                or_(
                    JobPostingRow.max_experience_years.is_(None),
                    JobPostingRow.max_experience_years >= min_experience,
                )
            )
        if max_experience is not None:
            clauses.append(
                or_(
                    JobPostingRow.min_experience_years.is_(None),
                    JobPostingRow.min_experience_years <= max_experience,
                )
            )
        # JSON array containment is portable enough for Postgres and SQLite query fallback.
        for field, raw in ((JobPostingRow.categories, categories), (JobPostingRow.skills, skills)):
            if raw:
                for item in raw.split(","):
                    clauses.append(field.contains([item]))
        column = (
            JobPostingRow.updated_at
            if sort.startswith("updated_at")
            else JobPostingRow.first_seen_at
        )
        direction = column.asc() if sort.endswith(":asc") else column.desc()
        if cursor:
            try:
                clauses.append(column < datetime.fromisoformat(cursor))
            except ValueError:
                raise HTTPException(400, "invalid cursor")
        rows = (
            (
                await session.execute(
                    select(JobPostingRow)
                    .where(and_(*clauses))
                    .order_by(direction, JobPostingRow.id)
                    .limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
        page = rows[:limit]
        next_cursor = page[-1].first_seen_at.isoformat() if len(rows) > limit else None
        return {
            "items": [row_dict(x) for x in page],
            "page": {"limit": limit, "next_cursor": next_cursor},
        }

    @app.get("/api/v1/jobs/{job_id}")
    async def job(job_id: UUID, session: AsyncSession = Depends(db)):
        row = await get_job(session, job_id)
        if not row:
            raise HTTPException(404, "job not found")
        return row_dict(row, True)

    @app.get("/api/v1/jobs/{job_id}/snapshots")
    @app.get("/api/v1/jobs/{job_id}/changes")
    async def snapshots(job_id: UUID, session: AsyncSession = Depends(db)):
        if not await get_job(session, job_id):
            raise HTTPException(404, "job not found")
        rows = (
            await session.execute(
                select(JobSnapshotRow)
                .where(JobSnapshotRow.job_posting_id == job_id)
                .order_by(JobSnapshotRow.created_at.desc())
            )
        ).scalars()
        return {
            "items": [
                {
                    "id": str(x.id),
                    "change_type": x.change_type,
                    "previous_status": x.previous_status,
                    "current_status": x.current_status,
                    "changed_fields": x.changed_fields,
                    "created_at": x.created_at,
                }
                for x in rows
            ]
        }

    @app.get("/api/v1/profiles")
    async def profile_list():
        return {"items": [x.model_dump() for x in profiles.items.values()]}

    @app.get("/api/v1/profiles/{profile_id}")
    async def profile(profile_id: str):
        if profile_id not in profiles.items:
            raise HTTPException(404, "profile not found")
        return profiles.get(profile_id).model_dump()

    @app.get("/api/v1/sources")
    async def source_list():
        return {
            "items": [
                {
                    "source": "WANTED",
                    "enabled": "WANTED" in adapters,
                    "status": "HEALTHY" if "WANTED" in adapters else "DISABLED",
                    "capabilities": {
                        "keyword_search": True,
                        "incremental_sync": True,
                        "status_check": True,
                        "posted_date": False,
                        "deadline": True,
                    },
                    "settings": {
                        "request_delay_seconds": settings.wanted_request_delay_seconds,
                        "max_concurrency": settings.wanted_max_concurrency,
                    },
                },
                {
                    "source": "SARAMIN",
                    "enabled": False,
                    "status": "DISABLED",
                    "disabled_reason": "access key is not configured",
                },
                {
                    "source": "JOBKOREA",
                    "enabled": False,
                    "status": "DISABLED",
                    "disabled_reason": "adapter is not configured",
                },
            ]
        }

    @app.post("/api/v1/admin/sync", dependencies=[Depends(admin)], status_code=202)
    async def sync_all(payload: SyncRequest):
        profile_id = payload.profile or settings.default_profile
        if profile_id not in profiles.items:
            raise HTTPException(404, "profile not found")
        runs = [await sync_service.sync(source, profile_id) for source in adapters]
        return {"run_ids": [str(x.id) for x in runs], "status": "COMPLETED"}

    @app.post("/api/v1/admin/sources/{source}/sync", dependencies=[Depends(admin)], status_code=202)
    async def sync_source(source: str, payload: SyncRequest):
        source = source.upper()
        if source not in adapters:
            raise HTTPException(400, "source unavailable")
        run = await sync_service.sync(source, payload.profile or settings.default_profile)
        return {"run_ids": [str(run.id)], "status": run.status}

    @app.post(
        "/api/v1/admin/sources/{source}/recheck", dependencies=[Depends(admin)], status_code=202
    )
    async def recheck_source(source: str, payload: SyncRequest):
        """Queue a source refresh; a source never changes status merely because search missed it."""
        return await sync_source(source, payload)

    @app.post("/api/v1/admin/jobs/{job_id}/recheck", dependencies=[Depends(admin)], status_code=202)
    async def recheck_job(job_id: UUID, session: AsyncSession = Depends(db)):
        row = await get_job(session, job_id)
        if not row:
            raise HTTPException(404, "job not found")
        if row.source not in adapters:
            raise HTTPException(400, "source unavailable")
        # The next source run performs the conservative detail check.  Returning a run id
        # keeps the request bounded instead of holding a dashboard connection open.
        run = await sync_service.sync(row.source, settings.default_profile)
        return {"run_ids": [str(run.id)], "status": run.status}

    @app.post("/api/v1/admin/profiles", dependencies=[Depends(admin)], status_code=201)
    async def create_profile(payload: SearchProfile, session: AsyncSession = Depends(db)):
        if await session.get(SearchProfileRow, payload.id):
            raise HTTPException(409, "profile already exists")
        session.add(
            SearchProfileRow(
                id=payload.id, display_name=payload.display_name, config=payload.model_dump()
            )
        )
        await session.commit()
        profiles.set(payload)
        return payload.model_dump()

    @app.put("/api/v1/admin/profiles/{profile_id}", dependencies=[Depends(admin)])
    async def update_profile(
        profile_id: str, payload: SearchProfile, session: AsyncSession = Depends(db)
    ):
        if profile_id != payload.id:
            raise HTTPException(400, "profile id cannot be changed")
        row = await session.get(SearchProfileRow, profile_id)
        if not row:
            raise HTTPException(404, "profile not found")
        row.display_name, row.config = payload.display_name, payload.model_dump()
        await session.commit()
        profiles.set(payload)
        return payload.model_dump()

    @app.delete(
        "/api/v1/admin/profiles/{profile_id}", dependencies=[Depends(admin)], status_code=204
    )
    async def delete_profile(profile_id: str, session: AsyncSession = Depends(db)):
        row = await session.get(SearchProfileRow, profile_id)
        if not row:
            raise HTTPException(404, "profile not found")
        await session.delete(row)
        await session.commit()
        profiles.remove(profile_id)

    @app.post("/api/v1/admin/profiles/reload", dependencies=[Depends(admin)])
    async def reload_profiles(session: AsyncSession = Depends(db)):
        await profiles.seed_and_load(session)
        return {"status": "reloaded", "count": len(profiles.items)}

    @app.get("/api/v1/admin/settings/schedule", dependencies=[Depends(admin)])
    async def get_schedule(session: AsyncSession = Depends(db)):
        value = await load_schedule_settings(session)
        return {"sync_cron": value.sync_cron, "recheck_cron": value.recheck_cron}

    @app.put("/api/v1/admin/settings/schedule", dependencies=[Depends(admin)])
    async def update_schedule(payload: ScheduleRequest, session: AsyncSession = Depends(db)):
        try:
            CronTrigger.from_crontab(payload.sync_cron)
            CronTrigger.from_crontab(payload.recheck_cron)
        except ValueError as exc:
            raise HTTPException(400, "cron must have five valid fields") from exc
        await save_schedule_settings(
            session,
            ScheduleSettings(sync_cron=payload.sync_cron, recheck_cron=payload.recheck_cron),
        )
        return {"sync_cron": payload.sync_cron, "recheck_cron": payload.recheck_cron}

    @app.get("/api/v1/admin/crawl-runs", dependencies=[Depends(admin)])
    async def crawl_runs(session: AsyncSession = Depends(db)):
        rows = (
            await session.execute(
                select(CrawlRunRow).order_by(CrawlRunRow.started_at.desc()).limit(100)
            )
        ).scalars()
        return {
            "items": [
                {
                    k: (str(v) if k == "id" else v)
                    for k, v in x.__dict__.items()
                    if not k.startswith("_")
                }
                for x in rows
            ]
        }

    @app.get("/api/v1/admin/crawl-runs/{run_id}", dependencies=[Depends(admin)])
    async def crawl_run(run_id: UUID, session: AsyncSession = Depends(db)):
        row = await session.get(CrawlRunRow, run_id)
        if not row:
            raise HTTPException(404, "crawl run not found")
        return {
            k: (str(v) if k == "id" else v)
            for k, v in row.__dict__.items()
            if not k.startswith("_")
        }

    @app.get("/api/v1/dashboard/summary")
    async def summary(session: AsyncSession = Depends(db)):
        counts = {
            s: (
                await session.scalar(
                    select(func.count())
                    .select_from(JobPostingRow)
                    .where(JobPostingRow.detected_status == s)
                )
            )
            or 0
            for s in ("ACTIVE", "CLOSED", "UNKNOWN", "DELETED")
        }
        total = sum(counts.values())
        recent = datetime.now(UTC) - timedelta(days=7)
        new = (
            await session.scalar(
                select(func.count())
                .select_from(JobPostingRow)
                .where(JobPostingRow.first_seen_at >= recent)
            )
        ) or 0
        last = (
            await session.execute(
                select(CrawlRunRow).order_by(CrawlRunRow.started_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
        return {
            "jobs": {
                "total": total,
                **{k.lower(): v for k, v in counts.items()},
                "new_last_7_days": new,
                "closed_last_7_days": 0,
            },
            "sources": {"enabled": len(adapters), "healthy": len(adapters), "failed": 0},
            "crawl": {
                "last_started_at": last.started_at if last else None,
                "last_finished_at": last.finished_at if last else None,
                "last_status": last.status if last else None,
                "next_run_at": None,
            },
        }

    return app
