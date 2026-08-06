from __future__ import annotations

import asyncio
import hmac
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID

from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ....bootstrap import Settings
from ....domain.model import JobChangeType, JobSource, SourceJobReference
from ....domain.services import content_hash, json_safe, normalize
from ....persistence import (
    Base,
    CrawlRunRow,
    JobPostingRow,
    JobProfileMatchRow,
    JobSnapshotRow,
    SearchProfileRow,
    get_job,
    session_factory,
)
from ....profiles import ProfileStore, SearchProfile
from ....runtime_settings import (
    RequestPacingSettings,
    ScheduleSettings,
    load_request_pacing_settings,
    load_schedule_settings,
    save_request_pacing_settings,
    save_schedule_settings,
    seed_request_pacing_settings,
    seed_schedule_settings,
)
from ....sources import (
    CorporateCareerSourceAdapter,
    JobKoreaJobSourceAdapter,
    LgCareerSourceAdapter,
    SaraminJobSourceAdapter,
    SaraminPublicJobSourceAdapter,
    WantedJobSourceAdapter,
)
from ....sync import SyncService
from ....tor import TorControlError, request_newnym


class SyncRequest(BaseModel):
    profile: str | None = None
    mode: str = "incremental"


class ScheduleRequest(BaseModel):
    sync_cron: str
    recheck_cron: str


class RequestPacingRequest(BaseModel):
    random_delay_enabled: bool
    random_delay_max_seconds: float = Field(0.5, ge=0, le=60)


class DeleteAllJobsRequest(BaseModel):
    confirm: Literal["DELETE_ALL"]


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
        "employment_type": row.employment_type,
        "experience": {
            "raw": row.experience_raw,
            "type": row.experience_type,
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
    adapters = {}
    if settings.wanted_enabled:
        adapters["WANTED"] = WantedJobSourceAdapter(
            settings.wanted_base_url,
            settings.http_timeout_seconds,
            settings.wanted_request_delay_seconds,
            settings.request_random_delay_enabled,
            settings.request_random_delay_max_seconds,
            settings.tor_socks_proxy_url if settings.tor_enabled else None,
        )
    if settings.saramin_enabled and settings.saramin_access_key:
        adapters["SARAMIN"] = SaraminJobSourceAdapter(
            settings.saramin_access_key, settings.http_timeout_seconds,
            random_delay_enabled=settings.request_random_delay_enabled,
            random_delay_max_seconds=settings.request_random_delay_max_seconds,
            proxy=settings.tor_socks_proxy_url if settings.tor_enabled else None,
            base_url=settings.saramin_base_url,
        )
    elif settings.saramin_public_enabled:
        adapters["SARAMIN"] = SaraminPublicJobSourceAdapter(
            settings.saramin_public_base_url,
            settings.http_timeout_seconds,
            settings.saramin_public_request_delay_seconds,
            settings.request_random_delay_enabled,
            settings.request_random_delay_max_seconds,
            settings.tor_socks_proxy_url if settings.tor_enabled else None,
        )
    if settings.jobkorea_enabled:
        adapters["JOBKOREA"] = JobKoreaJobSourceAdapter(
            settings.jobkorea_base_url,
            settings.http_timeout_seconds,
            settings.jobkorea_request_delay_seconds,
            settings.request_random_delay_enabled,
            settings.request_random_delay_max_seconds,
            settings.tor_socks_proxy_url if settings.tor_enabled else None,
        )
    corporate_sites = {
        "SAMSUNG": (settings.samsung_enabled, "https://www.samsungcareers.com/"),
        "LG": (settings.lg_enabled, "https://careers.lg.com/apply"),
        "HYUNDAI": (settings.hyundai_enabled, "https://talent.hyundai.com/apply/applyList.hc"),
    }
    for source, (enabled, listing_url) in corporate_sites.items():
        if enabled:
            adapters[source] = (
                LgCareerSourceAdapter(
                    settings.http_timeout_seconds,
                    random_delay_enabled=settings.request_random_delay_enabled,
                    random_delay_max_seconds=settings.request_random_delay_max_seconds,
                    proxy=settings.tor_socks_proxy_url if settings.tor_enabled else None,
                )
                if source == "LG"
                else CorporateCareerSourceAdapter(
                    JobSource(source), listing_url, settings.http_timeout_seconds,
                    random_delay_enabled=settings.request_random_delay_enabled,
                    random_delay_max_seconds=settings.request_random_delay_max_seconds,
                    proxy=settings.tor_socks_proxy_url if settings.tor_enabled else None,
                )
            )
    sync_service = SyncService(
        sessions, adapters, profiles, commit_batch_size=settings.sync_commit_batch_size
    )
    sync_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # SQLite makes local development work; production uses migration service.
        if settings.database_url.startswith("sqlite"):
            async with sessions.kw["bind"].begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            await profiles.seed_and_load(session)
            await seed_schedule_settings(session, settings.sync_cron, settings.recheck_cron)
            await seed_request_pacing_settings(
                session,
                settings.request_random_delay_enabled,
                settings.request_random_delay_max_seconds,
            )
            pacing = await load_request_pacing_settings(session)
        settings.request_random_delay_enabled = pacing.random_delay_enabled
        settings.request_random_delay_max_seconds = pacing.random_delay_max_seconds
        for adapter in adapters.values():
            adapter.random_delay_enabled = pacing.random_delay_enabled
            adapter.random_delay_max_seconds = pacing.random_delay_max_seconds
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
        profile_id: str | None = None,
        categories: str | None = None,
        skills: str | None = None,
        region: str | None = None,
        employment_types: str | None = None,
        experience_types: str | None = None,
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
        if profile_id:
            if profile_id not in profiles.items:
                raise HTTPException(404, "profile not found")
            clauses.append(
                JobPostingRow.id.in_(
                    select(JobProfileMatchRow.job_id).where(
                        JobProfileMatchRow.profile_id == profile_id
                    )
                )
            )
        if sources:
            clauses.append(JobPostingRow.source.in_(sources.split(",")))
        if region:
            clauses.append(JobPostingRow.region == region)
        if employment_types:
            clauses.append(JobPostingRow.employment_type.in_(employment_types.split(",")))
        if experience_types:
            clauses.append(JobPostingRow.experience_type.in_(experience_types.split(",")))
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
        sort_columns = {
            "deadline_date": JobPostingRow.deadline_date,
            "company_name": JobPostingRow.company_name,
            "title": JobPostingRow.title,
            "source": JobPostingRow.source,
            "region": JobPostingRow.region,
            "experience": JobPostingRow.min_experience_years,
            "employment_type": JobPostingRow.employment_type,
            "updated_at": JobPostingRow.updated_at,
            "first_seen_at": JobPostingRow.first_seen_at,
        }
        sort_name, _, sort_order = sort.partition(":")
        column = sort_columns.get(sort_name)
        if column is None:
            raise HTTPException(400, f"unsupported sort field: {sort_name}")
        ascending = sort_order != "desc"
        direction = (column.asc() if ascending else column.desc()).nulls_last()
        if cursor:
            try:
                if sort_name == "deadline_date":
                    cursor_value = date.fromisoformat(cursor)
                elif sort_name in {"updated_at", "first_seen_at"}:
                    cursor_value = datetime.fromisoformat(cursor)
                elif sort_name == "experience":
                    cursor_value = int(cursor)
                else:
                    cursor_value = cursor
                clauses.append(column < cursor_value if ascending else column > cursor_value)
            except ValueError:
                raise HTTPException(400, "invalid cursor")
        order_columns = [direction]
        # Keep pagination deterministic and make company name the common
        # ascending tie-breaker for every sort (title breaks company ties).
        if sort_name == "company_name":
            order_columns.append(JobPostingRow.title.asc().nulls_last())
        else:
            order_columns.append(JobPostingRow.company_name.asc().nulls_last())
        order_columns.append(JobPostingRow.id)
        rows = (
            (
                await session.execute(
                    select(JobPostingRow)
                    .where(and_(*clauses))
                    .order_by(*order_columns)
                    .limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
        page = rows[:limit]
        next_cursor = getattr(page[-1], column.key).isoformat() if len(rows) > limit else None
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
                    "enabled": "SARAMIN" in adapters,
                    "status": "HEALTHY" if "SARAMIN" in adapters else "DISABLED",
                    "disabled_reason": (
                        "API access key and public-page mode are not configured"
                        if "SARAMIN" not in adapters
                        else None
                    ),
                    "capabilities": {
                        "keyword_search": True,
                        "incremental_sync": True,
                        "status_check": True,
                        "posted_date": True,
                        "deadline": True,
                    },
                },
                {
                    "source": "JOBKOREA",
                    "enabled": "JOBKOREA" in adapters,
                    "status": "HEALTHY" if "JOBKOREA" in adapters else "DISABLED",
                    "disabled_reason": "adapter is not configured" if "JOBKOREA" not in adapters else None,
                    "capabilities": {
                        "keyword_search": True, "incremental_sync": True, "status_check": True,
                        "posted_date": True, "deadline": True,
                    },
                },
                *[
                    {
                        "source": source,
                        "enabled": source in adapters,
                        "status": "HEALTHY" if source in adapters else "DISABLED",
                        "disabled_reason": "adapter is not enabled" if source not in adapters else None,
                        "capabilities": {
                            "keyword_search": True,
                            "incremental_sync": True,
                            "status_check": True,
                            "posted_date": True,
                            "deadline": True,
                        },
                    }
                    for source in ("SAMSUNG", "LG", "HYUNDAI")
                ],
            ]
        }

    @app.post("/api/v1/admin/sync", dependencies=[Depends(admin)], status_code=202)
    async def sync_all(payload: SyncRequest, background_tasks: BackgroundTasks):
        profile_ids = [payload.profile] if payload.profile else list(profiles.items)
        if not profile_ids:
            raise HTTPException(404, "no profiles configured")
        missing_profiles = [item for item in profile_ids if item not in profiles.items]
        if missing_profiles:
            raise HTTPException(404, f"profile not found: {missing_profiles[0]}")
        profile_id = profile_ids[0]

        async def execute() -> None:
            if sync_lock.locked():
                return
            async with sync_lock:
                for source in adapters:
                    await sync_service.sync(
                        source,
                        profile_id,
                        profile_ids=profile_ids,
                    )

        background_tasks.add_task(execute)
        return {
            "status": "QUEUED",
            "message": "동기화가 백그라운드에서 시작됩니다.",
            "profiles": profile_ids,
        }

    @app.post("/api/v1/admin/sources/{source}/sync", dependencies=[Depends(admin)], status_code=202)
    async def sync_source(
        source: str, payload: SyncRequest, background_tasks: BackgroundTasks
    ):
        source = source.upper()
        if source not in adapters:
            raise HTTPException(400, "source unavailable")
        profile_id = payload.profile or settings.default_profile
        if profile_id not in profiles.items:
            raise HTTPException(404, "profile not found")

        async def execute() -> None:
            if sync_lock.locked():
                return
            async with sync_lock:
                await sync_service.sync(source, profile_id)

        background_tasks.add_task(execute)
        return {"status": "QUEUED", "message": f"{source} 동기화가 백그라운드에서 시작됩니다."}

    @app.post(
        "/api/v1/admin/sources/{source}/recheck", dependencies=[Depends(admin)], status_code=202
    )
    async def recheck_source(
        source: str, payload: SyncRequest, background_tasks: BackgroundTasks
    ):
        """Queue a source refresh; a source never changes status merely because search missed it."""
        return await sync_source(source, payload, background_tasks)

    @app.post("/api/v1/admin/jobs/{job_id}/recheck", dependencies=[Depends(admin)])
    async def recheck_job(job_id: UUID, session: AsyncSession = Depends(db)):
        row = await get_job(session, job_id)
        if not row:
            raise HTTPException(404, "job not found")
        if row.source not in adapters:
            raise HTTPException(400, "source unavailable")
        source_job = await adapters[row.source].fetch_detail(
            SourceJobReference(
                source=row.source, source_job_id=row.source_job_id, url=row.canonical_url
            )
        )
        values = normalize(
            source_job,
            today=datetime.now(UTC).date(),
            has_apply_action=bool(source_job.raw_payload.get("has_apply_action")),
        )
        digest = content_hash(values)
        old_status, old_hash = row.detected_status, row.content_hash
        changed_fields = [key for key, value in values.items() if getattr(row, key) != value]
        for key, value in values.items():
            setattr(row, key, value)
        row.content_hash = digest
        row.last_seen_at = row.last_checked_at = datetime.now(UTC)
        if old_hash != digest:
            change = (
                JobChangeType.STATUS_CHANGED.value
                if old_status != row.detected_status
                else JobChangeType.CONTENT_UPDATED.value
            )
            session.add(
                JobSnapshotRow(
                    job_posting_id=row.id,
                    change_type=change,
                    previous_status=old_status,
                    current_status=row.detected_status,
                    changed_fields=changed_fields,
                    content_hash=digest,
                    snapshot=json_safe(values),
                )
            )
        await session.commit()
        return row_dict(row, True)

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

    @app.delete("/api/v1/admin/jobs", dependencies=[Depends(admin)])
    async def delete_all_jobs(payload: DeleteAllJobsRequest, session: AsyncSession = Depends(db)):
        snapshots = (await session.execute(delete(JobSnapshotRow))).rowcount or 0
        jobs = (await session.execute(delete(JobPostingRow))).rowcount or 0
        await session.commit()
        return {"status": "DELETED", "deleted_jobs": jobs, "deleted_snapshots": snapshots}

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

    @app.get("/api/v1/admin/settings/request-pacing", dependencies=[Depends(admin)])
    async def get_request_pacing(session: AsyncSession = Depends(db)):
        value = await load_request_pacing_settings(session)
        return {
            "random_delay_enabled": value.random_delay_enabled,
            "random_delay_max_seconds": value.random_delay_max_seconds,
        }

    @app.put("/api/v1/admin/settings/request-pacing", dependencies=[Depends(admin)])
    async def update_request_pacing(
        payload: RequestPacingRequest, session: AsyncSession = Depends(db)
    ):
        value = RequestPacingSettings(
            random_delay_enabled=payload.random_delay_enabled,
            random_delay_max_seconds=payload.random_delay_max_seconds,
        )
        await save_request_pacing_settings(session, value)
        settings.request_random_delay_enabled = value.random_delay_enabled
        settings.request_random_delay_max_seconds = value.random_delay_max_seconds
        for adapter in adapters.values():
            adapter.random_delay_enabled = value.random_delay_enabled
            adapter.random_delay_max_seconds = value.random_delay_max_seconds
        return {
            "random_delay_enabled": value.random_delay_enabled,
            "random_delay_max_seconds": value.random_delay_max_seconds,
            "applied": True,
        }

    @app.post("/api/v1/admin/tor/newnym", dependencies=[Depends(admin)])
    async def tor_newnym():
        if not settings.tor_control_enabled:
            raise HTTPException(409, "Tor ControlPort is disabled")
        try:
            await request_newnym(
                settings.tor_control_host,
                settings.tor_control_port,
                settings.tor_control_password,
            )
        except TorControlError as exc:
            raise HTTPException(502, f"Tor ControlPort error: {exc}") from exc
        return {"status": "NEWNYM_SENT"}

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
        grouped = await session.execute(
            select(JobPostingRow.source, JobPostingRow.detected_status, func.count())
            .group_by(JobPostingRow.source, JobPostingRow.detected_status)
        )
        source_counts: dict[str, dict[str, int]] = {}
        for source, status, count in grouped:
            source_counts.setdefault(source, {}).update({status.lower(): count})
        recent_runs = (
            await session.execute(
                select(CrawlRunRow).order_by(CrawlRunRow.started_at.desc()).limit(200)
            )
        ).scalars()
        latest_by_source: dict[str, CrawlRunRow] = {}
        for run in recent_runs:
            latest_by_source.setdefault(run.source, run)
        source_names = ("WANTED", "SARAMIN", "JOBKOREA", "SAMSUNG", "LG", "HYUNDAI")
        source_details = []
        for source in source_names:
            values = source_counts.get(source, {})
            run = latest_by_source.get(source)
            source_details.append(
                {
                    "source": source,
                    "enabled": source in adapters,
                    "total": sum(values.values()),
                    "active": values.get("active", 0),
                    "closed": values.get("closed", 0),
                    "unknown": values.get("unknown", 0),
                    "last_started_at": run.started_at if run else None,
                    "last_finished_at": run.finished_at if run else None,
                    "last_status": run.status if run else None,
                }
            )
        return {
            "jobs": {
                "total": total,
                **{k.lower(): v for k, v in counts.items()},
                "new_last_7_days": new,
                "closed_last_7_days": 0,
            },
            "sources": {
                "enabled": len(adapters),
                "healthy": len(adapters),
                "failed": 0,
                "items": source_details,
            },
            "crawl": {
                "last_started_at": last.started_at if last else None,
                "last_finished_at": last.finished_at if last else None,
                "last_status": last.status if last else None,
                "next_run_at": None,
            },
        }

    return app
