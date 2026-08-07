from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime

from sqlalchemy import select

from .domain.model import JobChangeType, JobStatus, SourceSearchQuery
from .domain.services import content_hash, json_safe, normalize
from .persistence import (
    CrawlRunRow,
    JobPostingRow,
    JobProfileMatchRow,
    JobSnapshotRow,
    get_by_source,
    now,
)

logger = logging.getLogger(__name__)


def _query_key(query: str) -> str:
    """Return a stable key so equivalent profile queries are searched once.

    Profiles often contain the same broad term (for example, ``C++ 개발자``).
    Searching it once and attaching the result to every owning profile preserves
    recall while avoiding duplicate upstream requests.
    """
    return " ".join(query.split()).casefold()


def _status_for_missing(posting: JobPostingRow, today: date) -> tuple[str, str]:
    """Resolve a posting absent from a completed search without false closure."""
    if posting.deadline_date is not None and posting.deadline_date < today:
        return JobStatus.CLOSED.value, "deadline passed and absent from completed search"
    # A partial/profile-scoped search cannot prove that an undated or future-
    # deadline posting is closed. Keep the status already stored in the DB.
    return posting.detected_status, posting.status_reason or "stored status retained"


class SyncService:
    def __init__(self, sessions, adapters, profiles, commit_batch_size: int = 10):
        self.sessions, self.adapters, self.profiles = sessions, adapters, profiles
        self.commit_batch_size = max(1, commit_batch_size)

    async def reconcile_missing(self, source: str, started_at: datetime) -> int:
        """Mark active postings unseen during a complete multi-profile crawl.

        Profile crawls deliberately do not do this themselves because each one
        sees only a subset of a source.  The caller invokes this once after all
        profiles for the source have completed.
        """
        changed = 0
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(JobPostingRow).where(
                        JobPostingRow.source == source,
                        JobPostingRow.detected_status.in_(
                            (JobStatus.ACTIVE.value, JobStatus.UNKNOWN.value)
                        ),
                        JobPostingRow.last_seen_at < started_at,
                    )
                )
            ).scalars()
            for posting in rows:
                old_status = posting.detected_status
                target_status, reason = _status_for_missing(posting, datetime.now(UTC).date())
                posting.last_checked_at = now()
                if target_status == old_status and reason == posting.status_reason:
                    continue
                previous_hash = posting.content_hash
                posting.detected_status = target_status
                posting.status_reason = reason
                posting.content_hash = content_hash(
                    {"previous_hash": previous_hash, "status": target_status}
                )
                if target_status == JobStatus.CLOSED.value:
                    posting.closed_at = now()
                session.add(
                    JobSnapshotRow(
                        job_posting_id=posting.id,
                        change_type=JobChangeType.CLOSED.value
                        if target_status == JobStatus.CLOSED.value
                        else JobChangeType.STATUS_CHANGED.value,
                        previous_status=old_status,
                        current_status=target_status,
                        changed_fields=["detected_status", "status_reason"],
                        content_hash=posting.content_hash,
                        snapshot={
                            "detected_status": target_status,
                            "status_reason": reason,
                        },
                    )
                )
                changed += 1
            await session.commit()
        return changed

    async def sync(
        self,
        source: str,
        profile_id: str,
        profile_ids: list[str] | None = None,
        cancel_event: asyncio.Event | None = None,
        mark_missing: bool | None = None,
    ) -> CrawlRunRow:
        adapter = self.adapters[source]
        selected_ids = profile_ids or [profile_id]
        selected_profiles = [self.profiles.get(item) for item in selected_ids]
        # A single-profile crawl is only a partial view of a source.  It must
        # not mark jobs belonging to other profiles as UNKNOWN.
        if mark_missing is None:
            mark_missing = len(selected_profiles) > 1
        run_profile_id = "ALL_PROFILES" if len(selected_profiles) > 1 else profile_id
        logger.info(
            "sync started source=%s profiles=%s",
            source,
            ",".join(selected_ids),
        )
        async with self.sessions() as session:
            run = CrawlRunRow(source=source, profile_id=run_profile_id, status="RUNNING")
            session.add(run)
            await session.commit()
            try:
                refs = []
                profile_matches: dict[str, set[tuple[str, str]]] = {}
                if getattr(adapter, "profile_independent", False):
                    run.query_results = {"phase": "search", "profile": "ALL_PROFILES", "query": ""}
                    await session.commit()
                    refs = list(await adapter.search(SourceSearchQuery(query="")))
                    for ref in refs:
                        profile_matches[ref.source_job_id] = {
                            (profile.id, "") for profile in selected_profiles
                        }
                else:
                    # Group equivalent queries across profiles.  A query can be
                    # shared safely because profile matching is recorded for all
                    # profiles that requested it below.
                    query_groups: dict[str, dict[str, object]] = {}
                    for profile in selected_profiles:
                        queries = (
                            profile.source_queries.get(source, profile.queries)
                            + profile.company_queries.get(source, [])
                        )
                        for query in queries:
                            query = " ".join(str(query).split())
                            key = _query_key(query)
                            if not key:
                                continue
                            group = query_groups.setdefault(
                                key, {"query": query, "profiles": []}
                            )
                            group["profiles"].append((profile.id, query))
                    query_plan = list(query_groups.values())
                    total_queries = len(query_plan)
                    for completed_queries, group in enumerate(query_plan):
                        if cancel_event and cancel_event.is_set():
                            run.status = "CANCELLED"
                            run.finished_at = now()
                            await session.commit()
                            return run
                        run.query_results = {
                            "phase": "search",
                            "profile": ",".join(p[0] for p in group["profiles"]),
                            "profiles": [p[0] for p in group["profiles"]],
                            "query": group["query"],
                            "completed_queries": completed_queries,
                            "total_queries": total_queries,
                        }
                        await session.commit()
                        for ref in await adapter.search(SourceSearchQuery(query=group["query"])):
                            refs.append(ref)
                            for matched_profile, matched_query in group["profiles"]:
                                profile_matches.setdefault(ref.source_job_id, set()).add(
                                    (matched_profile, matched_query)
                                )
                        completed_queries += 1
                        run.searched_count = len({ref.source_job_id for ref in refs})
                        run.query_results = {
                            "phase": "search",
                            "profile": ",".join(p[0] for p in group["profiles"]),
                            "profiles": [p[0] for p in group["profiles"]],
                            "query": group["query"],
                            "completed_queries": completed_queries,
                            "total_queries": total_queries,
                        }
                        await session.commit()
                unique = {r.source_job_id: r for r in refs}
                run.searched_count = len(unique)
                run.query_results = {"phase": "fetch", "total_refs": len(unique)}
                await session.commit()
                for ref in unique.values():
                    if cancel_event and cancel_event.is_set():
                        run.status = "CANCELLED"
                        run.finished_at = now()
                        await session.commit()
                        logger.info(
                            "sync cancelled source=%s fetched=%s failed=%s",
                            source,
                            run.fetched_count,
                            run.failed_count,
                        )
                        return run
                    try:
                        raw = await adapter.fetch_detail(ref)
                        values = normalize(
                            raw,
                            today=datetime.now(UTC).date(),
                            has_apply_action=bool(raw.raw_payload.get("has_apply_action")),
                        )
                        digest = content_hash(values)
                        existing = await get_by_source(session, source, ref.source_job_id)
                        timestamp = now()
                        if existing is None:
                            row = JobPostingRow(
                                source=source,
                                source_job_id=ref.source_job_id,
                                content_hash=digest,
                                **values,
                            )
                            session.add(row)
                            await session.flush()
                            posting = row
                            session.add(
                                JobSnapshotRow(
                                    job_posting_id=row.id,
                                    change_type=JobChangeType.CREATED.value,
                                    current_status=row.detected_status,
                                    content_hash=digest,
                                    snapshot=json_safe(values),
                                )
                            )
                            run.created_count += 1
                        else:
                            posting = existing
                            old_status = existing.detected_status
                            if existing.content_hash != digest:
                                changed = [
                                    k for k, v in values.items() if getattr(existing, k) != v
                                ]
                                for key, value in values.items():
                                    setattr(existing, key, value)
                                existing.content_hash = digest
                                change = JobChangeType.CONTENT_UPDATED.value
                                if old_status != existing.detected_status:
                                    change = (
                                        JobChangeType.CLOSED.value
                                        if existing.detected_status == JobStatus.CLOSED
                                        else JobChangeType.REOPENED.value
                                        if old_status == JobStatus.CLOSED
                                        else JobChangeType.STATUS_CHANGED.value
                                    )
                                session.add(
                                    JobSnapshotRow(
                                        job_posting_id=existing.id,
                                        change_type=change,
                                        previous_status=old_status,
                                        current_status=existing.detected_status,
                                        changed_fields=changed,
                                        content_hash=digest,
                                        snapshot=json_safe(values),
                                    )
                                )
                                run.updated_count += 1
                            existing.last_seen_at = existing.last_checked_at = timestamp
                        for matched_profile, matched_query in profile_matches.get(
                            ref.source_job_id, set()
                        ):
                            match = await session.get(
                                JobProfileMatchRow, (posting.id, matched_profile)
                            )
                            if match is None:
                                session.add(
                                    JobProfileMatchRow(
                                        job_id=posting.id,
                                        profile_id=matched_profile,
                                        matched_query=matched_query,
                                    )
                                )
                            else:
                                match.last_matched_at = timestamp
                                if matched_query:
                                    match.matched_query = matched_query
                        run.fetched_count += 1
                    except Exception as exc:  # noqa: BLE001 - source failures must be isolated
                        run.failed_count += 1
                        run.error_summary[ref.url] = type(exc).__name__
                    if run.fetched_count and run.fetched_count % self.commit_batch_size == 0:
                        # Persist progress while a large source crawl is still running.
                        await session.commit()
                # Reconcile only after a complete search. A passed deadline is
                # definitive; otherwise retain the status already stored.
                missing = []
                if mark_missing:
                    missing = (
                        await session.execute(
                            select(JobPostingRow).where(
                                JobPostingRow.source == source,
                                JobPostingRow.detected_status.in_(
                                    (JobStatus.ACTIVE.value, JobStatus.UNKNOWN.value)
                                ),
                                JobPostingRow.source_job_id.not_in(unique),
                            )
                        )
                    ).scalars()
                for posting in missing:
                    old_status = posting.detected_status
                    target_status, reason = _status_for_missing(
                        posting, datetime.now(UTC).date()
                    )
                    posting.last_checked_at = now()
                    if target_status == old_status and reason == posting.status_reason:
                        continue
                    previous_hash = posting.content_hash
                    posting.detected_status = target_status
                    posting.status_reason = reason
                    posting.content_hash = content_hash(
                        {"previous_hash": previous_hash, "status": target_status}
                    )
                    if target_status == JobStatus.CLOSED.value:
                        posting.closed_at = now()
                    session.add(
                        JobSnapshotRow(
                            job_posting_id=posting.id,
                            change_type=JobChangeType.CLOSED.value
                            if target_status == JobStatus.CLOSED.value
                            else JobChangeType.STATUS_CHANGED.value,
                            previous_status=old_status,
                            current_status=target_status,
                            changed_fields=["detected_status", "status_reason"],
                            content_hash=posting.content_hash,
                            snapshot={
                                "detected_status": target_status,
                                "status_reason": reason,
                            },
                        )
                    )
                    run.updated_count += 1
                run.status = "PARTIAL_SUCCESS" if run.failed_count else "SUCCESS"
                if cancel_event and cancel_event.is_set():
                    run.status = "CANCELLED"
                run.finished_at = now()
                await session.commit()
                logger.info(
                    "sync finished source=%s status=%s searched=%s fetched=%s created=%s updated=%s failed=%s",
                    source,
                    run.status,
                    run.searched_count,
                    run.fetched_count,
                    run.created_count,
                    run.updated_count,
                    run.failed_count,
                )
                return run
            except Exception as exc:
                run.status = "FAILED"
                run.finished_at = now()
                run.error_summary = {"error": type(exc).__name__}
                await session.commit()
                logger.exception("sync failed source=%s", source)
                return run
