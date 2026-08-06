from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

JSONType = JSON().with_variant(JSONB, "postgresql")


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class JobPostingRow(Base):
    __tablename__ = "job_postings"
    __table_args__ = (UniqueConstraint("source", "source_job_id", name="uq_job_source_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(String(30), index=True)
    source_job_id: Mapped[str] = mapped_column(String(120))
    canonical_url: Mapped[str] = mapped_column(Text)
    company_name: Mapped[str] = mapped_column(String(300), index=True)
    title: Mapped[str] = mapped_column(String(500))
    detected_status: Mapped[str] = mapped_column(String(20), index=True)
    manual_status_override: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_raw: Mapped[str | None] = mapped_column(String(300), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    experience_raw: Mapped[str | None] = mapped_column(String(200), nullable=True)
    min_experience_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_experience_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    deadline_raw: Mapped[str | None] = mapped_column(String(200), nullable=True)
    deadline_date: Mapped[object | None] = mapped_column(Date, nullable=True, index=True)
    always_open: Mapped[bool] = mapped_column(Boolean, default=False)
    responsibilities: Mapped[list] = mapped_column(JSONType, default=list)
    requirements: Mapped[list] = mapped_column(JSONType, default=list)
    preferred_qualifications: Mapped[list] = mapped_column(JSONType, default=list)
    skills: Mapped[list] = mapped_column(JSONType, default=list)
    categories: Mapped[list] = mapped_column(JSONType, default=list)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, index=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now, index=True
    )


class JobSnapshotRow(Base):
    __tablename__ = "job_snapshots"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_posting_id: Mapped[UUID] = mapped_column(ForeignKey("job_postings.id"), index=True)
    change_type: Mapped[str] = mapped_column(String(30))
    previous_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    current_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    changed_fields: Mapped[list] = mapped_column(JSONType, default=list)
    content_hash: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CrawlRunRow(Base):
    __tablename__ = "crawl_runs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(String(30), index=True)
    profile_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    searched_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    closed_count: Mapped[int] = mapped_column(Integer, default=0)
    deleted_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    query_results: Mapped[dict] = mapped_column(JSONType, default=dict)
    error_summary: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SearchProfileRow(Base):
    __tablename__ = "search_profiles"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    config: Mapped[dict] = mapped_column(JSONType, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class RuntimeSettingRow(Base):
    __tablename__ = "runtime_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


def session_factory(url: str) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(create_async_engine(url, pool_pre_ping=True), expire_on_commit=False)


async def get_job(session: AsyncSession, job_id: UUID) -> JobPostingRow | None:
    return await session.get(JobPostingRow, job_id)


async def get_by_source(
    session: AsyncSession, source: str, source_job_id: str
) -> JobPostingRow | None:
    return (
        await session.execute(
            select(JobPostingRow).where(
                JobPostingRow.source == source, JobPostingRow.source_job_id == source_job_id
            )
        )
    ).scalar_one_or_none()
