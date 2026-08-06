from __future__ import annotations

from datetime import UTC, datetime

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


class SyncService:
    def __init__(self, sessions, adapters, profiles, commit_batch_size: int = 10):
        self.sessions, self.adapters, self.profiles = sessions, adapters, profiles
        self.commit_batch_size = max(1, commit_batch_size)

    async def sync(
        self, source: str, profile_id: str, profile_ids: list[str] | None = None
    ) -> CrawlRunRow:
        adapter = self.adapters[source]
        selected_ids = profile_ids or [profile_id]
        selected_profiles = [self.profiles.get(item) for item in selected_ids]
        run_profile_id = "ALL_PROFILES" if len(selected_profiles) > 1 else profile_id
        async with self.sessions() as session:
            run = CrawlRunRow(source=source, profile_id=run_profile_id, status="RUNNING")
            session.add(run)
            await session.commit()
            try:
                refs = []
                profile_matches: dict[str, set[tuple[str, str]]] = {}
                if getattr(adapter, "profile_independent", False):
                    refs = list(await adapter.search(SourceSearchQuery(query="")))
                    for ref in refs:
                        profile_matches[ref.source_job_id] = {
                            (profile.id, "") for profile in selected_profiles
                        }
                else:
                    for profile in selected_profiles:
                        queries = list(
                            dict.fromkeys(
                                profile.source_queries.get(source, profile.queries)
                                + profile.company_queries.get(source, [])
                            )
                        )
                        for query in queries:
                            for ref in await adapter.search(SourceSearchQuery(query=query)):
                                refs.append(ref)
                                profile_matches.setdefault(ref.source_job_id, set()).add(
                                    (profile.id, query)
                                )
                unique = {r.source_job_id: r for r in refs}
                run.searched_count = len(unique)
                for ref in unique.values():
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
                # A completed source search no longer contains this previously active
                # posting. It is not proof of closure, so preserve it as UNKNOWN.
                missing = (
                    await session.execute(
                        select(JobPostingRow).where(
                            JobPostingRow.source == source,
                            JobPostingRow.detected_status == JobStatus.ACTIVE.value,
                            JobPostingRow.source_job_id.not_in(unique),
                        )
                    )
                ).scalars()
                for posting in missing:
                    previous_hash = posting.content_hash
                    posting.detected_status = JobStatus.UNKNOWN.value
                    posting.status_reason = "not returned by completed source search"
                    posting.last_checked_at = now()
                    posting.content_hash = content_hash(
                        {"previous_hash": previous_hash, "status": "UNKNOWN"}
                    )
                    session.add(
                        JobSnapshotRow(
                            job_posting_id=posting.id,
                            change_type=JobChangeType.STATUS_CHANGED.value,
                            previous_status=JobStatus.ACTIVE.value,
                            current_status=JobStatus.UNKNOWN.value,
                            changed_fields=["detected_status", "status_reason"],
                            content_hash=posting.content_hash,
                            snapshot={
                                "detected_status": JobStatus.UNKNOWN.value,
                                "status_reason": posting.status_reason,
                            },
                        )
                    )
                    run.updated_count += 1
                run.status = "PARTIAL_SUCCESS" if run.failed_count else "SUCCESS"
                run.finished_at = now()
                await session.commit()
                return run
            except Exception as exc:  # noqa: BLE001 - persist failed run diagnostics
                run.status = "FAILED"
                run.finished_at = now()
                run.error_summary = {"error": type(exc).__name__}
                await session.commit()
                return run
