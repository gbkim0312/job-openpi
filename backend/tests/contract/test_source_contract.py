from job_collector.domain.model import JobSource, SourceJobPosting, SourceJobReference


def test_source_identity_is_preserved():
    ref = SourceJobReference(JobSource.WANTED, "315142", "https://example.test/wd/315142")
    detail = SourceJobPosting(ref.source, ref.source_job_id, ref.url, "C++", "Acme")
    assert (detail.source, detail.source_job_id) == (ref.source, ref.source_job_id)
