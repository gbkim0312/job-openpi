from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from urllib.parse import urlsplit, urlunsplit

from .model import JobCategory, SourceJobPosting, resolve_status

CATEGORY_KEYWORDS = {
    JobCategory.MOBILITY: ("모빌리티", "자동차", "차량", "automotive"),
    JobCategory.SDV: ("sdv", "software defined vehicle"),
    JobCategory.AUTOMOTIVE_SECURITY: ("차량 보안", "automotive security", "secure boot"),
    JobCategory.V2X: ("v2x", "c-v2x"),
    JobCategory.AUTOSAR: ("autosar",),
    JobCategory.EMBEDDED: ("임베디드", "embedded"),
    JobCategory.CPP: ("c++", "c/c++"),
    JobCategory.LINUX: ("linux",),
    JobCategory.NETWORK: ("network", "네트워크", "ethernet", "can"),
    JobCategory.PKI_CRYPTO: ("pki", "암호", "crypto", "hsm"),
    JobCategory.MIDDLEWARE: ("middleware", "미들웨어", "some/ip", "dds"),
    JobCategory.ROBOTICS: ("robot", "로봇"),
}


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def parse_experience(raw: str | None) -> tuple[int | None, int | None]:
    if not raw:
        return None, None
    numbers = [int(x) for x in re.findall(r"\d+", raw)]
    if not numbers:
        return None, None
    return (numbers[0], numbers[1]) if len(numbers) > 1 else (numbers[0], None)


def parse_deadline(raw: str | None) -> tuple[date | None, bool]:
    if not raw:
        return None, False
    if any(token in raw.lower() for token in ("상시", "always", "채용시")):
        return None, True
    for pattern in (
        r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})",
        r"(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})",
    ):
        match = re.search(pattern, raw)
        if match:
            year, month, day = map(int, match.groups())
            return date(year + 2000 if year < 100 else year, month, day), False
    return None, False


def classify(*values: object) -> set[str]:
    text = " ".join(str(v) for v in values if v).lower()
    return {
        category.value
        for category, terms in CATEGORY_KEYWORDS.items()
        if any(t in text for t in terms)
    }


def content_hash(fields: dict[str, object]) -> str:
    normalized = json.dumps(
        fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


def normalize(
    source_job: SourceJobPosting, *, today: date, has_apply_action: bool = False
) -> dict[str, object]:
    deadline, always_open = parse_deadline(source_job.raw_deadline)
    status, reason = resolve_status(
        source_job.raw_status, deadline, always_open, has_apply_action, today
    )
    min_years, max_years = parse_experience(source_job.raw_experience)
    categories = classify(
        source_job.raw_title,
        source_job.raw_company,
        source_job.responsibilities,
        source_job.requirements,
        source_job.skills,
    )
    skills = sorted(set(source_job.skills))
    return {
        "canonical_url": canonical_url(source_job.url),
        "company_name": source_job.raw_company or "Unknown",
        "title": source_job.raw_title,
        "detected_status": status.value,
        "source_status": source_job.raw_status,
        "status_reason": reason,
        "location_raw": source_job.raw_location,
        "experience_raw": source_job.raw_experience,
        "min_experience_years": min_years,
        "max_experience_years": max_years,
        "employment_type": source_job.raw_employment_type,
        "deadline_raw": source_job.raw_deadline,
        "deadline_date": deadline,
        "always_open": always_open,
        "responsibilities": list(source_job.responsibilities),
        "requirements": list(source_job.requirements),
        "preferred_qualifications": list(source_job.preferred_qualifications),
        "skills": skills,
        "categories": sorted(categories),
        "posted_at": source_job.posted_at,
    }
