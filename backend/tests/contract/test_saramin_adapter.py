import respx
from httpx import Response

from job_collector.domain.model import SourceJobReference, SourceSearchQuery
from job_collector.sources import SaraminJobSourceAdapter

PAYLOAD = {
    "jobs": {"job": [{
        "id": "s-1", "url": "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=1",
        "active": 1, "keyword": "C++, Linux",
        "posting-date": "2026-08-01T09:00:00+09:00", "expiration-date": "2026-08-31",
        "company": {"detail": {"name": "테스트회사"}},
        "position": {
            "title": "임베디드 개발자", "location": {"name": "서울 강남구"},
            "job-type": {"name": "정규직"}, "experience-level": {"name": "경력 2~3년"},
        },
    }]}
}


@respx.mock
async def test_saramin_search_and_detail():
    route = respx.get("https://oapi.saramin.co.kr/job-search").mock(return_value=Response(200, json=PAYLOAD))
    adapter = SaraminJobSourceAdapter("key", delay=0)
    refs = await adapter.search(SourceSearchQuery("개발자", page_size=10))
    assert route.called and refs == [SourceJobReference(adapter.source, "s-1", PAYLOAD["jobs"]["job"][0]["url"])]
    posting = await adapter.fetch_detail(refs[0])
    assert posting.raw_title == "임베디드 개발자"
    assert posting.raw_company == "테스트회사"
    assert posting.raw_experience == "경력 2~3년"
    assert posting.skills == ("C++", "Linux")
