from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class JobSource(StrEnum):
    WANTED = "WANTED"
    SARAMIN = "SARAMIN"
    JOBKOREA = "JOBKOREA"


class JobStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"
    DELETED = "DELETED"


class JobChangeType(StrEnum):
    CREATED = "CREATED"
    CONTENT_UPDATED = "CONTENT_UPDATED"
    STATUS_CHANGED = "STATUS_CHANGED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    DELETED = "DELETED"


class JobCategory(StrEnum):
    MOBILITY = "MOBILITY"
    SDV = "SDV"
    AUTOMOTIVE_SECURITY = "AUTOMOTIVE_SECURITY"
    V2X = "V2X"
    AUTOSAR = "AUTOSAR"
    EMBEDDED = "EMBEDDED"
    CPP = "CPP"
    LINUX = "LINUX"
    NETWORK = "NETWORK"
    PKI_CRYPTO = "PKI_CRYPTO"
    MIDDLEWARE = "MIDDLEWARE"
    ROBOTICS = "ROBOTICS"


@dataclass(frozen=True)
class SourceJobReference:
    source: JobSource
    source_job_id: str
    url: str


@dataclass(frozen=True)
class SourceJobPosting:
    source: JobSource
    source_job_id: str
    url: str
    raw_title: str
    raw_company: str | None
    raw_location: str | None = None
    raw_experience: str | None = None
    raw_employment_type: str | None = None
    raw_deadline: str | None = None
    raw_status: str | None = None
    responsibilities: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    preferred_qualifications: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    posted_at: datetime | None = None
    fetched_at: datetime | None = None
    raw_payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceSearchQuery:
    query: str
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True)
class SourceCapabilities:
    supports_keyword_search: bool
    supports_incremental_sync: bool
    supports_status_check: bool
    supports_posted_date: bool
    supports_deadline: bool


def resolve_status(
    raw_status: str | None,
    deadline_date: date | None,
    always_open: bool,
    has_apply_action: bool,
    current_date: date,
) -> tuple[JobStatus, str]:
    value = (raw_status or "").strip().lower()
    closed = (
        "채용 마감",
        "접수 마감",
        "지원 종료",
        "모집 종료",
        "공고 종료",
        "closed",
        "close",
        "마감",
    )
    if any(marker in value for marker in closed):
        return JobStatus.CLOSED, "explicit closed marker"
    active = ("active", "open", "채용중", "모집중", "지원 가능")
    if any(marker in value for marker in active):
        return JobStatus.ACTIVE, "explicit active marker"
    if deadline_date and deadline_date < current_date:
        return JobStatus.CLOSED, "deadline passed"
    if always_open and has_apply_action:
        return JobStatus.ACTIVE, "always open and apply action available"
    if has_apply_action:
        return JobStatus.ACTIVE, "apply action available"
    return JobStatus.UNKNOWN, "status could not be verified"
