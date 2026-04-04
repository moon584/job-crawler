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
        self.category_ids: set[str] = set()
        self.ensure_calls: list[tuple[str, list[str]]] = []
        self.marked_categories: list[str] = []
        self.purged_categories: list[str] = []
        self.cleared_categories: list[str] = []
        self.marked_companies: list[str] = []
        self.purged_companies: list[str] = []
        self.cleared_companies: list[str] = []
        self.touched_urls: list[tuple[str, int]] = []

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

    def fetch_category_ids(self, company_id: str) -> set[str]:
        return {cid for cid in self.category_ids if cid.startswith(company_id)}

    def ensure_categories_exist(self, company_id: str, category_ids: list[str]) -> list[str]:
        self.ensure_calls.append((company_id, list(category_ids)))
        created: list[str] = []
        for category_id in category_ids:
            if category_id not in self.category_ids:
                self.category_ids.add(category_id)
                created.append(category_id)
        return created

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

    def mark_jobs_deleted_by_category(self, company_id: str, category_id: str, job_type: int) -> int:
        self.marked_categories.append(f"{company_id}:{category_id}:{job_type}")
        return self.job_count_by_category.get(category_id, 0)

    def mark_jobs_deleted_by_company(self, company_id: str, job_type: int) -> int:
        self.marked_companies.append(f"{company_id}:{job_type}")
        return 0

    def touch_job_alive_by_url(self, job_url: str, job_type: int) -> bool:
        self.touched_urls.append((job_url, job_type))
        return True

    def purge_deleted_jobs_by_category(self, company_id: str, category_id: str, job_type: int) -> int:
        self.purged_categories.append(f"{company_id}:{category_id}:{job_type}")
        return 0

    def purge_deleted_jobs_by_company(self, company_id: str, job_type: int) -> int:
        self.purged_companies.append(f"{company_id}:{job_type}")
        return 0

    def clear_deleted_marks_by_category(self, company_id: str, category_id: str, job_type: int) -> int:
        self.cleared_categories.append(f"{company_id}:{category_id}:{job_type}")
        return 0

    def clear_deleted_marks_by_company(self, company_id: str, job_type: int) -> int:
        self.cleared_companies.append(f"{company_id}:{job_type}")
        return 0


class _FakeProvider:
    def __init__(self, extra: dict[str, object] | None = None) -> None:
        self.company_id = "C001"
        self.extra = extra or {}


def _make_record(crawled_at: datetime, *, category_id: str = "CAT001", job_url: str = "https://example.com/job/1") -> JobRecord:
    return JobRecord(
        id=None,
        company_id="C001",
        category_id=category_id,
        job_url=job_url,
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
        is_deleted=0,
        crawl_status=1,
        crawled_at=crawled_at,
        created_at=None,
    )


def test_persist_record_skips_when_job_url_exists() -> None:
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

    inserted = crawler._persist_record(record)

    assert inserted is True
    assert fake_db.update_payload is not None


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


def test_run_skips_existing_before_fetching_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeDB()
    fake_db.existing_job = {"id": "C001J00001"}
    fake_db.category_mappings = [
        CategoryMapping(
            db_category_id="CAT001",
            api_category_id="40001001",
            crawled_job_count=0,
            official_job_count=-1,
        )
    ]
    provider = _FakeProvider()
    provider.supports_auto_category = lambda: False
    provider.extract_post_id = lambda post: "1"
    provider.predict_job_url = lambda post: "https://example.com/job/1"
    crawler = JobCrawler(
        fake_db,
        http_client=object(),
        provider=provider,
        job_type=0,
    )
    monkeypatch.setattr(crawler, "_fetch_posts", lambda category_id, post_limit: [{"jobUnionId": "1"}])
    monkeypatch.setattr(
        crawler,
        "_fetch_detail",
        lambda post_id: (_ for _ in ()).throw(AssertionError("_fetch_detail should not be called for existing job_url")),
    )

    stats = crawler.run()

    assert stats.skipped_existing == 1
    assert stats.success == 0
    assert stats.failed == 0


def test_run_fetches_detail_when_pre_skip_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeDB()
    fake_db.existing_job = {"id": "C001J00001"}
    fake_db.category_mappings = [
        CategoryMapping(
            db_category_id="CAT001",
            api_category_id="40001001",
            crawled_job_count=0,
            official_job_count=-1,
        )
    ]
    provider = _FakeProvider({"skip_detail_if_exists": False})
    provider.supports_auto_category = lambda: False
    provider.extract_post_id = lambda post: "1"
    provider.predict_job_url = lambda post: "https://example.com/job/1"
    provider.build_job_record = lambda category_id, detail, crawled_at: _make_record(
        crawled_at,
        category_id=category_id,
        job_url="https://example.com/job/1",
    )
    crawler = JobCrawler(
        fake_db,
        http_client=object(),
        provider=provider,
        job_type=0,
    )
    monkeypatch.setattr(crawler, "_fetch_posts", lambda category_id, post_limit: [{"jobUnionId": "1"}])
    detail_called = {"value": False}

    def _fake_detail(post_id: str) -> dict[str, object]:
        detail_called["value"] = True
        return {"jobUnionId": post_id}

    monkeypatch.setattr(crawler, "_fetch_detail", _fake_detail)

    stats = crawler.run()

    assert detail_called["value"] is True
    assert stats.skipped_existing == 0
    assert stats.success == 1
    assert stats.failed == 0


def test_run_slow_mode_skips_only_when_existing_success(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake_db = _FakeDB()
    fake_db.existing_job = {"id": "C001J00001", "crawl_status": 1}
    fake_db.category_mappings = [
        CategoryMapping(
            db_category_id="CAT001",
            api_category_id="40001001",
            crawled_job_count=0,
            official_job_count=-1,
        )
    ]
    provider = _FakeProvider()
    provider.supports_auto_category = lambda: False
    provider.extract_post_id = lambda post: "1"
    provider.predict_job_url = lambda post: "https://example.com/job/1"
    crawler = JobCrawler(
        fake_db,
        http_client=object(),
        provider=provider,
        job_type=1,
        crawl_mode="slow",
    )
    monkeypatch.setattr(crawler, "_fetch_posts", lambda category_id, post_limit: [{"jobUnionId": "1"}])
    monkeypatch.setattr(
        crawler,
        "_fetch_detail",
        lambda post_id: (_ for _ in ()).throw(AssertionError("_fetch_detail should not be called for crawl_status=1")),
    )

    with caplog.at_level("INFO"):
        stats = crawler.run()

    assert stats.skipped_existing == 1
    assert stats.success == 0
    assert stats.failed == 0
    assert fake_db.marked_categories == ["C001:CAT001:1"]
    assert fake_db.purged_categories == ["C001:CAT001:1"]
    assert fake_db.touched_urls == [("https://example.com/job/1", 1)]
    assert "慢爬收尾统计 company=C001 category=CAT001 job_type=1" in "".join(caplog.messages)


def test_run_slow_mode_retries_existing_failed_job(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeDB()
    fake_db.existing_job = {"id": "C001J00001", "crawl_status": 0}
    fake_db.category_mappings = [
        CategoryMapping(
            db_category_id="CAT001",
            api_category_id="40001001",
            crawled_job_count=0,
            official_job_count=-1,
        )
    ]
    provider = _FakeProvider()
    provider.supports_auto_category = lambda: False
    provider.extract_post_id = lambda post: "1"
    provider.predict_job_url = lambda post: "https://example.com/job/1"
    provider.build_job_record = lambda category_id, detail, crawled_at: _make_record(
        crawled_at,
        category_id=category_id,
        job_url="https://example.com/job/1",
    )
    crawler = JobCrawler(
        fake_db,
        http_client=object(),
        provider=provider,
        job_type=1,
        crawl_mode="slow",
    )
    monkeypatch.setattr(crawler, "_fetch_posts", lambda category_id, post_limit: [{"jobUnionId": "1"}])
    detail_called = {"value": False}

    def _fake_detail(post_id: str) -> dict[str, object]:
        detail_called["value"] = True
        return {"jobUnionId": post_id}

    monkeypatch.setattr(crawler, "_fetch_detail", _fake_detail)

    stats = crawler.run()

    assert detail_called["value"] is True
    assert stats.skipped_existing == 0
    assert stats.success == 1
    assert stats.failed == 0


def test_run_auto_category_bootstraps_categories_from_rule_json(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake_db = _FakeDB()
    provider = _FakeProvider(
        {
            "auto_category_mode": True,
            "default_category_id": "C007DEFAULT",
            "default_api_category_id": "MEITUAN_ALL",
            "category_rules": [
                {"category_id": "C007A01", "match": {"jobFamily": "技术类"}},
            ],
        }
    )
    provider.company_id = "C007"
    provider.extract_post_id = lambda post: str(post.get("jobUnionId"))
    provider.resolve_category_id = lambda post, detail: "C007A01"
    provider.build_job_record = lambda category_id, detail, crawled_at: _make_record(crawled_at, category_id=category_id, job_url=f"https://example.com/{detail['jobUnionId']}")
    crawler = JobCrawler(
        fake_db,
        http_client=object(),
        provider=provider,
        job_type=0,
    )
    monkeypatch.setattr(crawler, "_fetch_posts", lambda category_id, post_limit: [{"jobUnionId": "1", "jobFamily": "技术类"}])
    monkeypatch.setattr(crawler, "_fetch_detail", lambda post_id: {"jobUnionId": post_id})
    monkeypatch.setattr(crawler, "_persist_record", lambda record: True)
    monkeypatch.setattr(crawler, "_handle_category_gap", lambda category_id, official_total: None)
    monkeypatch.setattr(crawler, "_refresh_category_counts", lambda category_id, official_total: None)

    with caplog.at_level("INFO"):
        stats = crawler._run_auto_category(post_limit=None)

    assert fake_db.ensure_calls
    _, ensured = fake_db.ensure_calls[0]
    assert "C007DEFAULT" in ensured
    assert "C007A01" in ensured
    assert stats.success == 1
    assert "自动分类命中统计" in "".join(caplog.messages)


def test_collect_auto_category_ids_filters_other_company_ids(caplog: pytest.LogCaptureFixture) -> None:
    extra_cfg: dict[str, object] = {
        "category_rules": [
            {"category_id": "C007A01", "match": {"jobFamily": "技术类"}},
            {"category_id": "C001A01", "match": {"jobFamily": "技术类"}},
        ]
    }

    with caplog.at_level("WARNING"):
        result = JobCrawler._collect_auto_category_ids(extra_cfg, "C007", "C007DEFAULT")

    assert result == ["C007DEFAULT", "C007A01"]
    assert "不属于公司 C007" in "".join(caplog.messages)


