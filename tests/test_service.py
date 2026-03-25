from __future__ import annotations

from datetime import UTC, datetime

import pytest

from crawler.models import CategoryMapping, JobRecord
from crawler.service import JobCrawler


class _FakeDB:
    def __init__(self) -> None:
        self.existing_job: dict[str, object] | None = None
        self.update_payload: tuple[str, dict[str, object]] | None = None
        self.category_mappings: list[CategoryMapping] = []
        self.synced_categories: list[tuple[str, int | None]] = []
        self.job_count_by_category: dict[str, int] = {}
        self.deleted_categories: list[str] = []

    def fetch_job_by_url(self, job_url: str) -> dict[str, object] | None:
        return self.existing_job

    def fetch_category_mappings(
        self,
        company_id: str,
        *,
        category_ids: list[str] | None = None,
        only_leaf: bool = True,
    ) -> list[CategoryMapping]:
        return list(self.category_mappings)

    def generate_next_job_id(self, company_id: str) -> str:  # pragma: no cover - not used in this test
        raise AssertionError("generate_next_job_id should not be called")

    def insert_job(self, params: dict[str, object]) -> None:  # pragma: no cover - not used in this test
        raise AssertionError("insert_job should not be called")

    def update_job(self, job_id: str, changes: dict[str, object]) -> None:
        self.update_payload = (job_id, changes)

    def sync_category_counts(self, category_id: str, official_total: int | None = None) -> int:
        self.synced_categories.append((category_id, official_total))
        current = self.job_count_by_category.get(category_id, 0)
        return current

    def count_jobs_in_category(self, category_id: str) -> int:
        return self.job_count_by_category.get(category_id, 0)

    def delete_jobs_by_category(self, category_id: str) -> int:
        removed = self.job_count_by_category.get(category_id, 0)
        self.deleted_categories.append(category_id)
        self.job_count_by_category[category_id] = 0
        return removed


class _FakeProvider:
    def __init__(self, extra: dict[str, object] | None = None) -> None:
        self.company_id = "C001"
        self.extra = extra or {}


def _make_record(crawled_at: datetime) -> JobRecord:
    return JobRecord(
        id=None,
        company_id="C001",
        category_id="CAT001",
        job_url="https://example.com/job/1",
        title="Example Role",
        salary="面议",
        job_type=0,
        education="本科",
        publish_time=crawled_at,
        location="深圳",
        description="desc",
        requirement="req",
        bonus=None,
        work_experience=None,
        crawl_status=1,
        crawled_at=crawled_at,
        created_at=None,
    )


def test_persist_record_refreshes_metadata_when_content_unchanged() -> None:
    crawled_at = datetime.now(UTC)
    record = _make_record(crawled_at)
    fake_db = _FakeDB()
    fake_db.existing_job = {
        "id": "C001J00001",
        "company_id": "C001",
        "category_id": "CAT001",
        "job_url": record.job_url,
        "title": record.title,
        "salary": record.salary,
        "job_type": record.job_type,
        "education": record.education,
        "publish_time": record.publish_time,
        "location": record.location,
        "description": record.description,
        "requirement": record.requirement,
        "bonus": record.bonus,
        "work_experience": record.work_experience,
        "crawl_status": 0,
        "crawled_at": datetime.now(UTC),
    }
    crawler = JobCrawler(
        fake_db,
        http_client=object(),
        provider=_FakeProvider(),
        job_type=0,
    )

    crawler._persist_record(record)

    assert fake_db.update_payload is not None
    job_id, changes = fake_db.update_payload
    assert job_id == "C001J00001"
    assert changes["crawl_status"] == record.crawl_status
    assert changes["crawled_at"] == record.crawled_at


def test_resolve_category_mappings_uses_default_when_database_empty() -> None:
    fake_db = _FakeDB()
    provider = _FakeProvider(
        {
            "default_category_id": "CATDEFAULT",
            "default_api_category_id": "4001001",
        }
    )
    crawler = JobCrawler(
        fake_db,
        http_client=object(),
        provider=provider,
        job_type=0,
    )

    mappings = crawler._resolve_category_mappings(None)

    assert len(mappings) == 1
    assert mappings[0].db_category_id == "CATDEFAULT"
    assert mappings[0].api_category_id == "40001001"


def test_resolve_category_mappings_fallback_for_missing_targets() -> None:
    fake_db = _FakeDB()
    fake_db.category_mappings = [CategoryMapping(db_category_id="CAT001", api_category_id="40001001")]
    provider = _FakeProvider(
        {
            "default_category_id": "CATDEFAULT",
            "default_api_category_id": "4001001",
        }
    )
    crawler = JobCrawler(
        fake_db,
        http_client=object(),
        provider=provider,
        job_type=0,
    )

    mappings = crawler._resolve_category_mappings(["cat002"])

    assert {m.db_category_id for m in mappings} == {"CAT001", "cat002"}
    fallback = next(mapping for mapping in mappings if mapping.db_category_id == "cat002")
    assert fallback.api_category_id == "40001001"


def test_resolve_category_mappings_raises_without_default() -> None:
    fake_db = _FakeDB()
    provider = _FakeProvider()
    crawler = JobCrawler(
        fake_db,
        http_client=object(),
        provider=provider,
        job_type=0,
    )

    with pytest.raises(ValueError):
        crawler._resolve_category_mappings(["CAT001"])


def test_should_skip_category_when_counts_match(caplog: pytest.LogCaptureFixture) -> None:
    fake_db = _FakeDB()
    crawler = JobCrawler(
        fake_db,
        http_client=object(),
        provider=_FakeProvider(),
        job_type=0,
    )
    mapping = CategoryMapping(
        db_category_id="CAT001",
        api_category_id="40001001",
        crawled_job_count=10,
        official_job_count=10,
    )

    with caplog.at_level("INFO"):
        should_skip = crawler._should_skip_category(mapping)

    assert should_skip is True
    assert "跳过" in "".join(caplog.messages)


def test_should_not_skip_when_official_unknown() -> None:
    fake_db = _FakeDB()
    crawler = JobCrawler(
        fake_db,
        http_client=object(),
        provider=_FakeProvider(),
        job_type=0,
    )
    mapping = CategoryMapping(
        db_category_id="CAT002",
        api_category_id="40001002",
        crawled_job_count=0,
        official_job_count=-1,
    )

    assert crawler._should_skip_category(mapping) is False


def test_refresh_category_counts_updates_official() -> None:
    fake_db = _FakeDB()
    crawler = JobCrawler(
        fake_db,
        http_client=object(),
        provider=_FakeProvider(),
        job_type=0,
    )

    crawler._refresh_category_counts("CAT001", official_total=12)

    assert fake_db.synced_categories == [("CAT001", 12)]


def test_refresh_category_counts_respects_dry_run() -> None:
    fake_db = _FakeDB()
    crawler = JobCrawler(
        fake_db,
        http_client=object(),
        provider=_FakeProvider(),
        job_type=0,
        dry_run=True,
    )

    crawler._refresh_category_counts("CAT001", official_total=8)

    assert fake_db.synced_categories == []


def test_handle_category_gap_deletes_when_existing_greater() -> None:
    fake_db = _FakeDB()
    fake_db.job_count_by_category["CAT001"] = 5
    crawler = JobCrawler(
        fake_db,
        http_client=object(),
        provider=_FakeProvider(),
        job_type=0,
    )

    crawler._handle_category_gap("CAT001", official_total=2)

    assert fake_db.deleted_categories == ["CAT001"]
    assert fake_db.job_count_by_category["CAT001"] == 0


def test_handle_category_gap_no_action_when_counts_match() -> None:
    fake_db = _FakeDB()
    fake_db.job_count_by_category["CAT001"] = 3
    crawler = JobCrawler(
        fake_db,
        http_client=object(),
        provider=_FakeProvider(),
        job_type=0,
    )

    crawler._handle_category_gap("CAT001", official_total=3)

    assert fake_db.deleted_categories == []
