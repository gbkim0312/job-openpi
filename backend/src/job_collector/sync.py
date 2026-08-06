from __future__ import annotations

from datetime import UTC, datetime

from .domain.model import JobChangeType, JobStatus, SourceSearchQuery
from .domain.services import content_hash, normalize
from .persistence import CrawlRunRow, JobPostingRow, JobSnapshotRow, get_by_source, now


class SyncService:
    def __init__(self, sessions, adapters, profiles):
        self.sessions, self.adapters, self.profiles = sessions, adapters, profiles

    async def sync(self, source: str, profile_id: str) -> CrawlRunRow:
        adapter = self.adapters[source]
        profile = self.profiles.get(profile_id)
        async with self.sessions() as session:
            run = CrawlRunRow(source=source, profile_id=profile_id, status="RUNNING")
            session.add(run)
            await session.commit()
            try:
                refs = []
                queries = profile.source_queries.get(source, profile.queries)
                for query in queries:
                    refs.extend(await adapter.search(SourceSearchQuery(query=query)))
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
                            session.add(
                                JobSnapshotRow(
                                    job_posting_id=row.id,
                                    change_type=JobChangeType.CREATED.value,
                                    current_status=row.detected_status,
                                    content_hash=digest,
                                    snapshot=values,
                                )
                            )
                            run.created_count += 1
                        else:
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
                                        snapshot=values,
                                    )
                                )
                                run.updated_count += 1
                            existing.last_seen_at = existing.last_checked_at = timestamp
                        run.fetched_count += 1
                    except Exception as exc:  # noqa: BLE001 - source failures must be isolated
                        run.failed_count += 1
                        run.error_summary[ref.url] = type(exc).__name__
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
