from datetime import UTC, datetime

from job_collector.domain.model import SourceJobReference
from job_collector.sources import SaraminPublicJobSourceAdapter, parse_saramin_public_detail


def test_saramin_public_detail_parser():
    adapter = SaraminPublicJobSourceAdapter("https://www.saramin.co.kr")
    reference = SourceJobReference(adapter.source, "123", "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=123")
    posting = parse_saramin_public_detail(
        '<meta property="og:title" content="[테스트회사] C++ 개발자 - 사람인">'
        '<meta name="description" content="테스트회사,C++ 개발자, 경력:경력 3년, 마감일:2026-08-31">',
        reference,
        datetime.now(UTC),
    )
    assert posting.raw_title == "C++ 개발자"
    assert posting.raw_company == "테스트회사"
    assert posting.raw_experience == "경력 3년"
    assert posting.raw_deadline == "2026-08-31"
