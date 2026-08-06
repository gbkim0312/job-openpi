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


def test_saramin_public_detail_ignores_title_words_before_metadata():
    adapter = SaraminPublicJobSourceAdapter("https://www.saramin.co.kr")
    reference = SourceJobReference(adapter.source, "456", "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=456")
    posting = parse_saramin_public_detail(
        '<meta property="og:title" content="[회사] 경력 채용 공고 - 사람인">'
        '<meta name="description" content="회사, 경력 채용 공고, 경력:신입/경력, 학력:무관, 마감일:2026-08-31">',
        reference,
        datetime.now(UTC),
    )
    assert posting.raw_experience == "신입/경력"


def test_saramin_public_search_metadata_fills_location_and_employment():
    adapter = SaraminPublicJobSourceAdapter("https://www.saramin.co.kr")
    reference = SourceJobReference(adapter.source, "789", "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=789")
    posting = parse_saramin_public_detail(
        '<meta property="og:title" content="[회사] 개발자 - 사람인">'
        '<meta name="description" content="회사, 개발자, 경력:신입/경력, 마감일:2026-08-31">',
        reference,
        datetime.now(UTC),
        "IT개발·데이터 회사 개발자 ~ 08/31 홈페이지 지원 서울 강남구 신입·경력 대졸↑ 정규직·계약직 C++",
    )
    assert posting.raw_location == "서울 강남구"
    assert posting.raw_employment_type == "정규직·계약직"
