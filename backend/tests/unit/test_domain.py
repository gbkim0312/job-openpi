from datetime import date
from types import SimpleNamespace

from job_collector.domain.model import JobStatus, resolve_status
from job_collector.domain.services import canonical_url, content_hash, parse_experience
from job_collector.sync import _status_for_missing

TODAY = date(2026, 8, 6)


def test_explicit_closed_is_closed():
    assert resolve_status("채용 마감", None, False, True, TODAY)[0] == JobStatus.CLOSED


def test_past_deadline_is_closed():
    assert resolve_status(None, date(2020, 1, 1), False, True, TODAY)[0] == JobStatus.CLOSED


def test_apply_is_active():
    assert resolve_status(None, None, False, True, TODAY)[0] == JobStatus.ACTIVE


def test_unknown_is_preserved():
    assert resolve_status(None, None, False, False, TODAY)[0] == JobStatus.UNKNOWN


def test_missing_expired_posting_is_closed():
    posting = SimpleNamespace(
        deadline_date=date(2020, 1, 1), detected_status="ACTIVE", status_reason=None
    )
    assert _status_for_missing(posting, TODAY) == (
        "CLOSED",
        "deadline passed and absent from completed search",
    )


def test_missing_future_deadline_retains_stored_status():
    posting = SimpleNamespace(
        deadline_date=date(2099, 1, 1), detected_status="ACTIVE", status_reason="stored"
    )
    assert _status_for_missing(posting, TODAY) == ("ACTIVE", "stored")


def test_experience_range():
    assert parse_experience("경력 3~8년") == (3, 8)


def test_hash_is_stable():
    assert content_hash({"b": [2, 1], "a": "x"}) == content_hash({"a": "x", "b": [2, 1]})


def test_saramin_detail_url_keeps_rec_idx():
    assert canonical_url(
        "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=54596713"
    ).endswith("/zf_user/jobs/relay/view?rec_idx=54596713")
