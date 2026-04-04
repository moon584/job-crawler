from __future__ import annotations

import logging
import queue
import threading
from contextlib import contextmanager
from typing import Dict, Iterable, Iterator, List, Optional, Set

import pymysql
from pymysql.cursors import DictCursor

from .config import Settings
from .models import CategoryMapping
from .utils import normalize_category_id


class Database:
    """封装MySQL操作的轻量封装层（中文注释）。"""

    def __init__(self, settings: Settings, max_connections: int = 10) -> None:
        self._settings = settings
        self._max_connections = max_connections
        self._pool: queue.Queue[pymysql.connections.Connection] = queue.Queue(maxsize=max_connections)
        self._pool_lock = threading.Lock()
        self._current_connections = 0

    def _create_connection(self) -> pymysql.connections.Connection:
        return pymysql.connect(
            host=self._settings.db_host,
            port=self._settings.db_port,
            user=self._settings.db_user,
            password=self._settings.db_password,
            database=self._settings.db_name,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
            read_timeout=30,
            write_timeout=30,
        )

    def _get_connection(self) -> pymysql.connections.Connection:
        try:
            conn = self._pool.get_nowait()
            try:
                conn.ping(reconnect=True)
            except Exception:
                conn = self._create_connection()
            return conn
        except queue.Empty:
            with self._pool_lock:
                if self._current_connections < self._max_connections:
                    self._current_connections += 1
                    create_new = True
                else:
                    create_new = False
            if create_new:
                try:
                    return self._create_connection()
                except Exception:
                    with self._pool_lock:
                        self._current_connections -= 1
                    raise
            conn = self._pool.get(block=True, timeout=60)
            try:
                conn.ping(reconnect=True)
            except Exception:
                conn = self._create_connection()
            return conn

    def _release_connection(self, conn: pymysql.connections.Connection) -> None:
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            try:
                conn.close()
            except Exception:
                pass
            with self._pool_lock:
                self._current_connections -= 1

    @contextmanager
    def cursor(self) -> Iterator[DictCursor]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            cursor.close()
            self._release_connection(conn)

    def fetch_category_mappings(
        self,
        company_id: str,
        *,
        category_ids: Optional[List[str]] = None,
        only_leaf: bool = True,
    ) -> List[CategoryMapping]:
        """按需返回分类映射，可选只取叶子节点或指定ID（中文注释：便于交互选择分类）。"""
        select_sql = "SELECT c.id, c.categoryid, c.crawled_job_count, c.official_job_count FROM category c"
        joins: List[str] = []
        conditions: List[str] = ["c.categoryid IS NOT NULL", "c.id LIKE %s"]
        params: List[object] = [f"{company_id}%"]
        if only_leaf:
            joins.append("LEFT JOIN category child ON child.parent_id = c.id")
            conditions.append("child.id IS NULL")
        if category_ids:
            placeholders = ",".join(["%s"] * len(category_ids))
            conditions.append(f"c.id IN ({placeholders})")
            params.extend(category_ids)
        query = " ".join([select_sql] + joins)
        query += " WHERE " + " AND ".join(conditions)
        with self.cursor() as cur:
            cur.execute(query, tuple(params))
            rows = cur.fetchall()
        mappings: List[CategoryMapping] = []
        for row in rows:
            try:
                normalized_id = normalize_category_id(row["categoryid"])
            except ValueError as exc:
                logging.error(
                    "分类 %s 的 categoryid '%s' 非法：%s",
                    row["id"],
                    row["categoryid"],
                    exc,
                )
                continue
            mappings.append(
                CategoryMapping(
                    db_category_id=row["id"],
                    api_category_id=normalized_id,
                    crawled_job_count=int(row.get("crawled_job_count") or 0),
                    official_job_count=int(row.get("official_job_count") or 0),
                )
            )
        return mappings

    def fetch_job_by_url(self, job_url: str) -> Optional[Dict[str, object]]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM job WHERE job_url=%s", (job_url,))
            row = cur.fetchone()
        return row

    def fetch_category_ids(self, company_id: str) -> Set[str]:
        """返回公司下所有分类ID（不要求 categoryid 字段）."""
        with self.cursor() as cur:
            cur.execute("SELECT id FROM category WHERE id LIKE %s", (f"{company_id}%",))
            rows = cur.fetchall()
        return {str(row["id"]) for row in rows if row.get("id")}

    def ensure_categories_exist(self, company_id: str, category_ids: Iterable[str]) -> List[str]:
        """批量创建缺失分类，返回本次新增的分类ID列表。"""
        normalized_ids = []
        seen: Set[str] = set()
        for raw in category_ids:
            cid = str(raw).strip()
            if not cid or cid in seen:
                continue
            seen.add(cid)
            normalized_ids.append(cid)
        if not normalized_ids:
            return []

        existing_ids = self.fetch_category_ids(company_id)
        missing_ids = [cid for cid in normalized_ids if cid not in existing_ids]
        if not missing_ids:
            return []

        with self.cursor() as cur:
            for category_id in missing_ids:
                # 自动补齐一级分类节点，名称先使用ID，后续可在管理端调整。
                cur.execute(
                    "INSERT INTO category (id, name, parent_id, level, categoryid) VALUES (%s, %s, %s, %s, %s)",
                    (category_id, category_id, company_id, 0, None),
                )
        return missing_ids

    def generate_next_job_id(self, company_id: str) -> str:
        with self.cursor() as cur:
            cur.execute(
                "SELECT id FROM job WHERE company_id=%s ORDER BY id",
                (company_id,),
            )
            rows = cur.fetchall()
        existing_ids = [row["id"] for row in rows]
        return self._compute_next_job_id(company_id, existing_ids)

    @staticmethod
    def _compute_next_job_id(company_id: str, existing_ids: List[str]) -> str:
        prefix = f"{company_id}J"
        expected = 1
        for job_id in sorted(existing_ids):
            suffix = Database._extract_suffix(job_id, prefix)
            if suffix is None:
                continue
            if suffix > expected:
                break
            if suffix == expected:
                expected += 1
        return f"{company_id}J{expected:05d}"

    @staticmethod
    def _extract_suffix(job_id: str, prefix: str) -> Optional[int]:
        if not job_id.startswith(prefix):
            return None
        remainder = job_id[len(prefix) :]
        try:
            return int(remainder)
        except (TypeError, ValueError):
            return None

    def insert_job(self, job_values: Dict[str, object]) -> None:
        columns = ",".join(job_values.keys())
        placeholders = ",".join(["%s"] * len(job_values))
        sql = f"INSERT INTO job ({columns}) VALUES ({placeholders})"
        with self.cursor() as cur:
            cur.execute(sql, tuple(job_values.values()))

    def update_job(self, job_id: str, changes: Dict[str, object]) -> None:
        if not changes:
            return
        assignments = ",".join([f"{col}=%s" for col in changes.keys()])
        sql = f"UPDATE job SET {assignments} WHERE id=%s"
        params = list(changes.values()) + [job_id]
        with self.cursor() as cur:
            cur.execute(sql, params)

    def count_jobs_in_category(self, category_id: str) -> int:
        """统计指定分类当前已写入的职位数量。"""
        with self.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM job WHERE category_id=%s", (category_id,))
            row = cur.fetchone() or {"total": 0}
        return int(row["total"] or 0)

    def mark_jobs_deleted_by_category_count(self, category_id: str) -> int:
        """直接把某分类下所有岗位软删（由于增量更新，常用于 fast 模式刷新某分类）"""
        with self.cursor() as cur:
            cur.execute("UPDATE job SET is_deleted=1 WHERE category_id=%s", (category_id,))
            affected = cur.rowcount or 0
        return affected

    def mark_jobs_deleted_by_category(self, company_id: str, category_id: str, job_type: int) -> int:
        """慢爬准备阶段：按 company+category+job_type 标记待删除（is_deleted=1）。"""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE job SET is_deleted=1 WHERE company_id=%s AND category_id=%s AND job_type=%s",
                (company_id, category_id, job_type),
            )
            affected = cur.rowcount or 0
        return affected

    def mark_jobs_deleted_by_company(self, company_id: str, job_type: int) -> int:
        """慢爬自动分类准备阶段：先将公司+job_type 下职位标记为待删除（is_deleted=1）。"""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE job SET is_deleted=1 WHERE company_id=%s AND job_type=%s",
                (company_id, job_type),
            )
            affected = cur.rowcount or 0
        return affected

    def touch_job_alive_by_url(self, job_url: str, job_type: int, crawled_at: datetime) -> bool:
        """命中列表中的岗位即视为本次已抓到，取消待删除标记（is_deleted=0）并更新时间。"""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE job SET is_deleted=0, crawled_at=%s WHERE job_url=%s AND job_type=%s",
                (crawled_at, job_url, job_type),
            )
            affected = cur.rowcount or 0
        return affected > 0

    def soft_delete_unseen_jobs_by_category(self, company_id: str, category_id: str, job_type: int, before_time: datetime) -> int:
        """慢爬收尾：按 company+category+job_type 将 crawled_at 早于本次爬虫开始时间的记录软删（is_deleted=1）。"""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE job SET is_deleted=1 WHERE company_id=%s AND category_id=%s AND job_type=%s AND crawled_at < %s",
                (company_id, category_id, job_type, before_time),
            )
            affected = cur.rowcount or 0
        return affected

    def soft_delete_unseen_jobs_by_company(self, company_id: str, job_type: int, before_time: datetime) -> int:
        """慢爬收尾：将整个公司+job_type 下 crawled_at 早于本次爬虫开始时间的记录软删（is_deleted=1）。"""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE job SET is_deleted=1 WHERE company_id=%s AND job_type=%s AND crawled_at < %s",
                (company_id, job_type, before_time),
            )
            affected = cur.rowcount or 0
        return affected

    def clear_deleted_marks_by_category(self, company_id: str, category_id: str, job_type: int) -> int:
        """慢爬异常回滚：按 company+category+job_type 撤销待删除标记。"""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE job SET is_deleted=0 WHERE company_id=%s AND category_id=%s AND job_type=%s AND is_deleted=1",
                (company_id, category_id, job_type),
            )
            affected = cur.rowcount or 0
        return affected

    def clear_deleted_marks_by_company(self, company_id: str, job_type: int) -> int:
        """慢爬异常回滚：恢复公司+job_type 下标记位，避免中断后状态残留。"""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE job SET is_deleted=0 WHERE company_id=%s AND job_type=%s AND is_deleted=1",
                (company_id, job_type),
            )
            affected = cur.rowcount or 0
        return affected

    def sync_category_counts(self, category_id: str, official_total: Optional[int] = None) -> int:
        """同步分类的爬取/官网职位数量，返回最新 crawled 数量。"""
        crawled_total = self.count_jobs_in_category(category_id)
        with self.cursor() as cur:
            if official_total is None:
                cur.execute(
                    "UPDATE category SET crawled_job_count=%s WHERE id=%s",
                    (crawled_total, category_id),
                )
            else:
                cur.execute(
                    "UPDATE category SET crawled_job_count=%s, official_job_count=%s WHERE id=%s",
                    (crawled_total, max(official_total, 0), category_id),
                )
        return crawled_total

    def rollback(self) -> None:
        pass  # Rollback is now handled automatically within the cursor context manager

    def close(self) -> None:
        with self._pool_lock:
            while not self._pool.empty():
                try:
                    conn = self._pool.get_nowait()
                    conn.close()
                except Exception:
                    pass
            self._current_connections = 0

