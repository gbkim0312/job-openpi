from datetime import UTC, datetime

from job_collector.domain.model import SourceJobReference
from job_collector.sources import JobKoreaJobSourceAdapter, parse_jobkorea_detail


def test_jobkorea_public_html_parser():
    adapter = JobKoreaJobSourceAdapter("https://www.jobkorea.co.kr")
    reference = SourceJobReference(
        adapter.source, "123", "https://www.jobkorea.co.kr/Recruit/GI_Read/123"
    )
    posting = parse_jobkorea_detail(
        '''<html><head><meta name="writer" content="테스트회사">
        <meta property="og:title" content="테스트회사 채용 - C++ 개발자 | 잡코리아">
        <script type="application/ld+json">{"@type":"JobPosting","title":"C++ 개발자","datePosted":"2026-08-01","validThrough":"2026-08-31","experienceRequirements":"경력 3년","employmentType":"FULL_TIME","hiringOrganization":{"name":"테스트회사"},"jobLocation":{"address":{"streetAddress":"서울 강남구"}}}</script></head></html>''',
        reference,
        datetime.now(UTC),
    )
    assert posting.raw_title == "C++ 개발자"
    assert posting.raw_company == "테스트회사"
    assert posting.raw_location == "서울 강남구"


def test_jobkorea_meta_description_experience_fallback():
    adapter = JobKoreaJobSourceAdapter("https://www.jobkorea.co.kr")
    reference = SourceJobReference(adapter.source, "124", "https://www.jobkorea.co.kr/Recruit/GI_Read/124")
    posting = parse_jobkorea_detail(
        '<meta name="description" content="경력 : 경력무관 , 학력 : 학력무관, 마감일 : 2026.09.21">'
        '<meta property="og:title" content="회사 채용 - 개발자 | 잡코리아">'
        '<meta name="writer" content="회사">',
        reference,
        datetime.now(UTC),
    )
    assert posting.raw_experience == "경력무관"
    assert posting.raw_deadline == "2026.09.21"
