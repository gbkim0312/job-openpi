from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import UTC, datetime

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
    return SourceJobPosting(
        reference.source,
        reference.source_job_id,
        reference.url,
        title,
        company,
        raw_status="채용 마감" if closed else source_status or None,
        responsibilities=_text_list(soup, "주요업무"),
        requirements=_text_list(soup, "자격요건"),
        preferred_qualifications=_text_list(soup, "우대사항"),
        fetched_at=fetched_at,
        raw_payload={
            "json_ld": json_ld,
            "source_data": next_data,
            "has_apply_action": has_apply_action,
        },
    )
