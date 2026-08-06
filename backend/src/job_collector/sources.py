from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .domain.model import (
    JobSource,
    SourceCapabilities,
    SourceJobPosting,
    SourceJobReference,
    SourceSearchQuery,
)


class SourceError(Exception):
    pass


class SourceNotFoundError(SourceError):
    pass


class SourceParseError(SourceError):
    pass


class JobSourcePort(ABC):
    @property
    @abstractmethod
    def source(self) -> JobSource: ...
    @property
    @abstractmethod
    def capabilities(self) -> SourceCapabilities: ...
    @abstractmethod
    async def search(self, query: SourceSearchQuery) -> Sequence[SourceJobReference]: ...
    @abstractmethod
    async def fetch_detail(self, reference: SourceJobReference) -> SourceJobPosting: ...


class WantedJobSourceAdapter(JobSourcePort):
    """Conservative public-page adapter; it never bypasses access controls."""

    def __init__(self, base_url: str, timeout: float = 20, delay: float = 1.5):
        self.base_url, self.timeout, self.delay = base_url.rstrip("/"), timeout, delay
        self._last_request = 0.0

    @property
    def source(self):
        return JobSource.WANTED

    @property
    def capabilities(self):
        return SourceCapabilities(True, True, True, False, True)

    async def _get(self, url: str, params: dict | None = None) -> str:
        pause = self.delay - (asyncio.get_running_loop().time() - self._last_request)
        if pause > 0:
            await asyncio.sleep(pause)
        async with httpx.AsyncClient(
            timeout=self.timeout, headers={"User-Agent": "job-collector/0.1"}
        ) as client:
            response = await client.get(url, params=params)
            self._last_request = asyncio.get_running_loop().time()
        if response.status_code == 404:
            raise SourceNotFoundError(url)
        response.raise_for_status()
        return response.text

    async def search(self, query: SourceSearchQuery) -> Sequence[SourceJobReference]:
        payload = json.loads(
            await self._get(
                f"{self.base_url}/api/chaos/search/v1/position",
                {"query": query.query, "page": query.page},
            )
        )
        refs: dict[str, SourceJobReference] = {}
        for item in payload.get("data", []):
            job_id = str(item.get("id", ""))
            if job_id:
                refs[job_id] = SourceJobReference(
                    self.source, job_id, f"{self.base_url}/wd/{job_id}"
                )
        return list(refs.values())[: query.page_size]

    async def fetch_detail(self, reference: SourceJobReference) -> SourceJobPosting:
        html = await self._get(reference.url)
        return parse_wanted_detail(html, reference, datetime.now(UTC))


class JobKoreaJobSourceAdapter(JobSourcePort):
    """Public JobKorea search/detail pages, with conservative request pacing."""

    def __init__(self, base_url: str, timeout: float = 20, delay: float = 1.5):
        self.base_url, self.timeout, self.delay = base_url.rstrip("/"), timeout, delay
        self._last_request = 0.0

    @property
    def source(self):
        return JobSource.JOBKOREA

    @property
    def capabilities(self):
        return SourceCapabilities(True, True, True, True, True)

    async def _get(self, url: str, params: dict[str, object] | None = None) -> str:
        pause = self.delay - (asyncio.get_running_loop().time() - self._last_request)
        if pause > 0:
            await asyncio.sleep(pause)
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": "job-collector/0.1 (+public-page-collector)"},
            follow_redirects=True,
        ) as client:
            response = await client.get(url, params=params)
            self._last_request = asyncio.get_running_loop().time()
        if response.status_code == 404:
            raise SourceNotFoundError(url)
        response.raise_for_status()
        return response.text

    async def search(self, query: SourceSearchQuery) -> Sequence[SourceJobReference]:
        html = await self._get(f"{self.base_url}/Search/", {"stext": query.query})
        soup = BeautifulSoup(html, "lxml")
        refs: dict[str, SourceJobReference] = {}
        pattern = re.compile(r"/Recruit/GI_Read/(\d+)")
        for anchor in soup.select("a[href]"):
            href = str(anchor.get("href") or "")
            match = pattern.search(href)
            if match:
                job_id = match.group(1)
                refs[job_id] = SourceJobReference(
                    self.source, job_id, urljoin(self.base_url, href.split("?")[0])
                )
        start = max(0, (query.page - 1) * query.page_size)
        return list(refs.values())[start : start + query.page_size]

    async def fetch_detail(self, reference: SourceJobReference) -> SourceJobPosting:
        html = await self._get(reference.url)
        return parse_jobkorea_detail(html, reference, datetime.now(UTC))


class SaraminPublicJobSourceAdapter(JobSourcePort):
    """Public Saramin search/detail pages; no API key or private endpoint is used."""

    def __init__(self, base_url: str, timeout: float = 20, delay: float = 1.5):
        self.base_url, self.timeout, self.delay = base_url.rstrip("/"), timeout, delay
        self._last_request = 0.0

    @property
    def source(self):
        return JobSource.SARAMIN

    @property
    def capabilities(self):
        return SourceCapabilities(True, True, True, True, True)

    async def _get(self, url: str, params: dict[str, object] | None = None) -> str:
        pause = self.delay - (asyncio.get_running_loop().time() - self._last_request)
        if pause > 0:
            await asyncio.sleep(pause)
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": "job-collector/0.1 (+public-page-collector)"},
            follow_redirects=True,
        ) as client:
            response = await client.get(url, params=params)
            self._last_request = asyncio.get_running_loop().time()
        if response.status_code == 404:
            raise SourceNotFoundError(url)
        response.raise_for_status()
        return response.text

    async def search(self, query: SourceSearchQuery) -> Sequence[SourceJobReference]:
        html = await self._get(
            f"{self.base_url}/zf_user/search", {"searchword": query.query, "recruitPage": query.page}
        )
        soup = BeautifulSoup(html, "lxml")
        refs: dict[str, SourceJobReference] = {}
        pattern = re.compile(r"/zf_user/jobs/relay/view[^\"']*?rec_idx(?:=|%3D)(\d+)")
        for anchor in soup.select("a[href]"):
            href = str(anchor.get("href") or "").replace("&amp;", "&")
            match = pattern.search(href)
            if match:
                job_id = match.group(1)
                refs[job_id] = SourceJobReference(
                    self.source,
                    job_id,
                    f"{self.base_url}/zf_user/jobs/relay/view?rec_idx={job_id}",
                )
        start = max(0, (query.page - 1) * query.page_size)
        return list(refs.values())[start : start + query.page_size]

    async def fetch_detail(self, reference: SourceJobReference) -> SourceJobPosting:
        html = await self._get(reference.url)
        return parse_saramin_public_detail(html, reference, datetime.now(UTC))


def parse_saramin_public_detail(
    html: str, reference: SourceJobReference, fetched_at: datetime
) -> SourceJobPosting:
    soup = BeautifulSoup(html, "lxml")
    og_title = soup.select_one('meta[property="og:title"]')
    title_text = str(og_title.get("content") or "") if og_title else ""
    title = title_text.split("] ", 1)[-1].split(" - 사람인", 1)[0].strip()
    description = soup.select_one('meta[name="description"]')
    summary = str(description.get("content") or "") if description else ""
    company = summary.split(",", 1)[0].strip() or None
    if not title:
        heading = soup.select_one("h1, .jv_title")
        title = heading.get_text(" ", strip=True) if heading else ""
    if not title:
        raise SourceParseError("Saramin public job title unavailable")
    deadline_match = re.search(
        r"(?:^|,\s*)마감일\s*:\s*(\d{4}[-.]\d{1,2}[-.]\d{1,2})", summary
    )
    experience_match = re.search(r"(?:^|,\s*)경력\s*:\s*([^,]+)", summary)
    raw_text = soup.get_text(" ", strip=True)
    closed = any(marker in raw_text for marker in ("채용 마감", "접수 마감", "모집 마감"))
    return SourceJobPosting(
        reference.source,
        reference.source_job_id,
        reference.url,
        title,
        company,
        raw_experience=experience_match.group(1).strip() if experience_match else None,
        raw_deadline=deadline_match.group(1) if deadline_match else None,
        raw_status="closed" if closed else "active",
        fetched_at=fetched_at,
        raw_payload={"meta_description": summary, "has_apply_action": not closed},
    )


def parse_jobkorea_detail(
    html: str, reference: SourceJobReference, fetched_at: datetime
) -> SourceJobPosting:
    soup = BeautifulSoup(html, "lxml")
    json_ld: dict[str, object] = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            candidate = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        candidates = candidate if isinstance(candidate, list) else [candidate]
        json_ld = next(
            (x for x in candidates if isinstance(x, dict) and x.get("@type") == "JobPosting"),
            json_ld,
        )
    title = str(json_ld.get("title") or "")
    company_data = json_ld.get("hiringOrganization")
    company = company_data.get("name") if isinstance(company_data, dict) else None
    heading = soup.select_one("h1, .tit_job")
    title = title or (heading.get_text(strip=True) if heading else "")
    og_title = soup.select_one('meta[property="og:title"]')
    if not title and og_title and og_title.get("content"):
        title = str(og_title["content"]).split(" 채용 - ", 1)[-1].split(" | 잡코리아", 1)[0]
    if not company:
        writer = soup.select_one('meta[name="writer"]')
        company = str(writer["content"]).strip() if writer and writer.get("content") else None
    if not title:
        raise SourceParseError("JobKorea job title unavailable")
    location_data = json_ld.get("jobLocation")
    address = location_data.get("address") if isinstance(location_data, dict) else None
    location = address.get("streetAddress") if isinstance(address, dict) else None
    experience = str(json_ld.get("experienceRequirements") or "") or None
    employment = str(json_ld.get("employmentType") or "") or None
    deadline = str(json_ld.get("validThrough") or "") or None
    posted = None
    if json_ld.get("datePosted"):
        try:
            posted = datetime.fromisoformat(str(json_ld["datePosted"]))
        except ValueError:
            pass
    raw = soup.get_text(" ", strip=True)
    closed = any(marker in raw for marker in ("채용 마감", "접수 마감", "공고가 종료"))
    return SourceJobPosting(
        reference.source, reference.source_job_id, reference.url, title, company,
        raw_location=location, raw_experience=experience, raw_employment_type=employment,
        raw_deadline=deadline, raw_status="closed" if closed else "active",
        posted_at=posted, fetched_at=fetched_at,
        raw_payload={"json_ld": json_ld, "has_apply_action": not closed},
    )


class SaraminJobSourceAdapter(JobSourcePort):
    """Adapter for Saramin's official Open API (job-search endpoint)."""

    def __init__(
        self,
        access_key: str,
        timeout: float = 20,
        delay: float = 0.2,
        base_url: str = "https://oapi.saramin.co.kr",
    ):
        self.access_key, self.timeout, self.delay = access_key, timeout, delay
        self.base_url, self._last_request = base_url.rstrip("/"), 0.0

    @property
    def source(self):
        return JobSource.SARAMIN

    @property
    def capabilities(self):
        return SourceCapabilities(True, True, True, True, True)

    async def _get(self, params: dict[str, object]) -> dict[str, object]:
        pause = self.delay - (asyncio.get_running_loop().time() - self._last_request)
        if pause > 0:
            await asyncio.sleep(pause)
        request_params = {
            "access-key": self.access_key,
            "fields": "posting-date expiration-date",
            **params,
        }
        async with httpx.AsyncClient(
            timeout=self.timeout, headers={"Accept": "application/json"}
        ) as client:
            response = await client.get(f"{self.base_url}/job-search", params=request_params)
            self._last_request = asyncio.get_running_loop().time()
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise SourceParseError("Saramin response is not an object")
        if payload.get("code") not in (None, 0, "0"):
            raise SourceError(str(payload.get("message") or "Saramin API error"))
        return payload

    @staticmethod
    def _items(payload: dict[str, object]) -> list[dict[str, object]]:
        jobs = payload.get("jobs")
        items = jobs.get("job", []) if isinstance(jobs, dict) else []
        if isinstance(items, dict):
            items = [items]
        return [item for item in items if isinstance(item, dict)]

    async def search(self, query: SourceSearchQuery) -> Sequence[SourceJobReference]:
        payload = await self._get({
            "keywords": query.query,
            "start": max(0, (query.page - 1) * query.page_size),
            "count": min(query.page_size, 110),
            "sort": "pd",
        })
        refs: dict[str, SourceJobReference] = {}
        for item in self._items(payload):
            job_id = str(item.get("id") or "")
            url = str(item.get("url") or "")
            if job_id and url:
                refs[job_id] = SourceJobReference(self.source, job_id, url)
        return list(refs.values())

    async def fetch_detail(self, reference: SourceJobReference) -> SourceJobPosting:
        payload = await self._get({"id": reference.source_job_id, "count": 1})
        item = next(
            (x for x in self._items(payload) if str(x.get("id")) == reference.source_job_id),
            None,
        )
        if item is None:
            raise SourceNotFoundError(reference.url)
        return parse_saramin_job(item, reference, datetime.now(UTC))


def _saramin_value(value: object, key: str = "name") -> str | None:
    if isinstance(value, dict):
        value = value.get(key)
    return str(value).strip() if value is not None and str(value).strip() else None


def _parse_saramin_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def parse_saramin_job(
    item: dict[str, object], reference: SourceJobReference, fetched_at: datetime
) -> SourceJobPosting:
    position = item.get("position") if isinstance(item.get("position"), dict) else {}
    company = item.get("company") if isinstance(item.get("company"), dict) else {}
    detail = company.get("detail") if isinstance(company.get("detail"), dict) else company
    experience = position.get("experience-level") if isinstance(position.get("experience-level"), dict) else {}
    location = _saramin_value(position.get("location"))
    job_type = _saramin_value(position.get("job-type"))
    title = _saramin_value(position.get("title")) or ""
    if not title:
        raise SourceParseError("Saramin job title unavailable")
    keywords = tuple(x.strip() for x in str(item.get("keyword") or "").split(",") if x.strip())
    return SourceJobPosting(
        reference.source, reference.source_job_id, str(item.get("url") or reference.url), title,
        _saramin_value(detail), raw_location=location,
        raw_experience=_saramin_value(experience), raw_employment_type=job_type,
        raw_deadline=str(
            item.get("expiration-date") or _saramin_value(item.get("close-type")) or ""
        )
        or None,
        raw_status="active" if item.get("active") in (1, "1", True) else "closed",
        skills=keywords, posted_at=_parse_saramin_datetime(item.get("posting-date")),
        fetched_at=fetched_at,
        raw_payload={
            "saramin": item,
            "has_apply_action": item.get("active") in (1, "1", True),
        },
    )


def _text_list(soup: BeautifulSoup, label: str) -> tuple[str, ...]:
    heading = soup.find(
        lambda t: (
            t.name in ("h2", "h3", "strong")
            and label.lower() in t.get_text(" ", strip=True).lower()
        )
    )
    if not heading:
        return ()
    parent = heading.parent
    return tuple(x.get_text(" ", strip=True) for x in parent.select("li") if x.get_text(strip=True))


def _structured_lines(value: object) -> tuple[str, ...]:
    """Convert the source's structured multi-line descriptions without inventing data."""
    if not isinstance(value, str):
        return ()
    return tuple(
        line.lstrip("-•· ").strip() for line in value.splitlines() if line.lstrip("-•· ").strip()
    )


def parse_wanted_detail(
    html: str, reference: SourceJobReference, fetched_at: datetime
) -> SourceJobPosting:
    soup = BeautifulSoup(html, "lxml")
    json_ld = next(
        (
            json.loads(x.string)
            for x in soup.select('script[type="application/ld+json"]')
            if x.string and "JobPosting" in x.string
        ),
        {},
    )
    if isinstance(json_ld, list):
        json_ld = next((x for x in json_ld if x.get("@type") == "JobPosting"), {})
    next_data = {}
    next_script = soup.select_one("script#__NEXT_DATA__")
    if next_script and next_script.string:
        try:
            next_data = (
                json.loads(next_script.string)
                .get("props", {})
                .get("pageProps", {})
                .get("initialData", {})
            )
        except json.JSONDecodeError:
            next_data = {}
    title = json_ld.get("title") or (
        soup.select_one("h1").get_text(strip=True) if soup.select_one("h1") else ""
    )
    company = (
        (json_ld.get("hiringOrganization") or {}).get("name")
        if isinstance(json_ld.get("hiringOrganization"), dict)
        else None
    )
    company = company or (soup.select_one('[data-testid="company-name"]') or soup.select_one("h2"))
    company = (
        company if isinstance(company, str) else (company.get_text(strip=True) if company else None)
    )
    if not title:
        raise SourceParseError("job title unavailable")
    raw = soup.get_text(" ", strip=True)
    source_status = str(next_data.get("status") or "")
    closed = source_status.lower() in {"close", "closed", "end", "ended"} or any(
        x in raw for x in ("채용 마감", "접수 마감", "지원 종료")
    )
    apply_labels = ("지원하기", "지원 하기", "바로 지원", "apply")
    has_apply_action = any(
        any(label in element.get_text(" ", strip=True).lower() for label in apply_labels)
        and not element.has_attr("disabled")
        for element in soup.find_all(("a", "button"))
    )
    address = next_data.get("address") if isinstance(next_data.get("address"), dict) else {}
    raw_location = (
        " ".join(
            str(address.get(key, "")).strip()
            for key in ("location", "district")
            if address.get(key)
        )
        or None
    )
    career = next_data.get("career") if isinstance(next_data.get("career"), dict) else {}
    career_from, career_to = career.get("annual_from"), career.get("annual_to")
    if career.get("is_newbie") and not career_from:
        raw_experience = "신입"
    elif career_from is not None:
        raw_experience = f"경력 {career_from}" + (
            f"~{career_to}년" if career_to and career_to < 100 else "년"
        )
    else:
        raw_experience = None
    employment = {"regular": "정규직", "contract": "계약직", "intern": "인턴"}.get(
        str(next_data.get("employment_type") or "").lower(),
        str(next_data.get("employment_type") or "") or None,
    )
    due_time = next_data.get("due_time")
    raw_deadline = str(due_time) if due_time else ("상시채용" if due_time is None else None)
    return SourceJobPosting(
        reference.source,
        reference.source_job_id,
        reference.url,
        title,
        company,
        raw_location=raw_location,
        raw_experience=raw_experience,
        raw_employment_type=employment,
        raw_deadline=raw_deadline,
        raw_status="채용 마감" if closed else source_status or None,
        responsibilities=_structured_lines(next_data.get("main_tasks"))
        or _text_list(soup, "주요업무"),
        requirements=_structured_lines(next_data.get("requirements"))
        or _text_list(soup, "자격요건"),
        preferred_qualifications=_structured_lines(next_data.get("preferred_points"))
        or _text_list(soup, "우대사항"),
        fetched_at=fetched_at,
        raw_payload={
            "json_ld": json_ld,
            "source_data": next_data,
            "has_apply_action": has_apply_action,
        },
    )
