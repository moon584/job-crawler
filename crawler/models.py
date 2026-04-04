from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import threading
from typing import Dict, Optional


@dataclass(slots=True)
class CategoryMapping:
    """数据库分类ID与官网分类ID的映射（中文注释）。"""

    db_category_id: str
    api_category_id: Optional[str]
    crawled_job_count: int = 0
    official_job_count: int = 0


@dataclass(slots=True)
class JobRecord:
    """规范化后的职位信息记录（中文注释）。"""

    id: Optional[str]
    company_id: str
    category_id: str
    job_url: str
    title: str
    salary: str
    job_type: int
    education: Optional[str]
    publish_time: Optional[datetime]
    location: Optional[str]
    description: str
    requirement: Optional[str]
    bonus: Optional[str]
    work_experience: Optional[str]
    is_deleted: int
    crawl_status: int
    crawled_at: datetime
    created_at: Optional[datetime]

    def as_sql_params(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "company_id": self.company_id,
            "category_id": self.category_id,
            "job_url": self.job_url,
            "title": self.title,
            "salary": self.salary,
            "job_type": self.job_type,
            "education": self.education,
            "publish_time": self.publish_time,
            "location": self.location,
            "description": self.description,
            "requirement": self.requirement,
            "bonus": self.bonus,
            "work_experience": self.work_experience,
            "is_deleted": self.is_deleted,
            "crawl_status": self.crawl_status,
            "crawled_at": self.crawled_at,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class CrawlStats:
    """爬虫统计信息，便于最终日志输出（中文注释）。"""

    total_posts: int = 0
    success: int = 0
    failed: int = 0
    list_failures: int = 0
    detail_failures: int = 0
    per_category: Dict[str, int] = field(default_factory=dict)
    skipped_existing: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, init=False)

    def record_category(self, category_id: str, count: int) -> None:
        with self._lock:
            self.per_category[category_id] = self.per_category.get(category_id, 0) + count

    def record_success(self) -> None:
        with self._lock:
            self.total_posts += 1
            self.success += 1

    def record_failure(self) -> None:
        with self._lock:
            self.total_posts += 1
            self.failed += 1

    def record_list_failure(self) -> None:
        with self._lock:
            self.list_failures += 1

    def record_detail_failure(self) -> None:
        with self._lock:
            self.detail_failures += 1

    def record_skip_existing(self) -> None:
        with self._lock:
            self.skipped_existing += 1
