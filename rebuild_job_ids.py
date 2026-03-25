from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence, Tuple
from uuid import uuid4

from crawler.config import Settings
from crawler.db import Database

ORDER_BY_SQL = {
    "created_at": "created_at IS NULL, created_at ASC, id ASC",
    "publish_time": "publish_time IS NULL, publish_time ASC, id ASC",
    "job_url": "job_url ASC, id ASC",
}

MAX_JOB_ID_LENGTH = 16


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量重排 job.id，兼顾批量和精细场景。")
    parser.add_argument(
        "--company-id",
        action="append",
        dest="company_ids",
        help="仅处理指定公司，可重复传参；未指定则遍历所有 company_id。",
    )
    parser.add_argument(
        "--category-id",
        action="append",
        dest="category_ids",
        help="仅处理指定分类，可重复传参；默认包含该公司的全部分类。",
    )
    parser.add_argument(
        "--sort-by",
        choices=sorted(ORDER_BY_SQL.keys()),
        default="created_at",
        help="决定旧职位的排序方式，默认 created_at。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="仅处理前 N 条匹配的职位，默认全量。",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="重新编号的起始序号，默认 1。",
    )
    parser.add_argument(
        "--preview",
        type=int,
        default=5,
        help="日志预览展示的条数，默认 5。",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写入数据库。")
    parser.add_argument("--env-file", help="自定义 .env 路径。")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="日志等级，默认 INFO。",
    )
    parser.add_argument(
        "--backup-dir",
        default="backups",
        help="备份 SQL 输出目录，默认 backups。",
    )
    args = parser.parse_args()
    if args.start_index < 1:
        parser.error("--start-index 必须为正整数")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit 必须大于 0")
    if args.preview < 1:
        parser.error("--preview 必须大于 0")
    return args


def fetch_target_companies(db: Database, specified: Sequence[str] | None) -> List[str]:
    if specified:
        return sorted({item.strip().upper() for item in specified if item and item.strip()})
    with db.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT company_id FROM job WHERE company_id IS NOT NULL ORDER BY company_id"
        )
        rows = cur.fetchall()
    return [row["company_id"].upper() for row in rows if row.get("company_id")]


def fetch_jobs(
    db: Database,
    *,
    company_id: str,
    category_ids: Sequence[str] | None,
    sort_by: str,
    limit: int | None,
) -> List[Dict[str, object]]:
    clauses = [
        "SELECT id, company_id, category_id, created_at, publish_time, job_url",
        "FROM job",
        "WHERE company_id=%s",
    ]
    params: List[object] = [company_id]
    if category_ids:
        placeholders = ",".join(["%s"] * len(category_ids))
        clauses.append(f"AND category_id IN ({placeholders})")
        params.extend(category_ids)
    clauses.append(f"ORDER BY {ORDER_BY_SQL[sort_by]}")
    if limit is not None:
        clauses.append("LIMIT %s")
        params.append(limit)
    query = " ".join(clauses)
    with db.cursor() as cur:
        cur.execute(query, tuple(params))
        return cur.fetchall()


def infer_suffix_width(company_id: str, rows: Sequence[Dict[str, object]]) -> int:
    prefix = f"{company_id}J"
    width = 5
    for row in rows:
        job_id = row.get("id")
        if isinstance(job_id, str) and job_id.startswith(prefix):
            width = max(width, len(job_id) - len(prefix))
    return width


def build_plan(
    *,
    rows: Sequence[Dict[str, object]],
    company_id: str,
    start_index: int,
) -> Tuple[List[Tuple[str, str]], int]:
    if not rows:
        return ([], 5)
    width = infer_suffix_width(company_id, rows)
    prefix = f"{company_id}J"
    if len(prefix) + width > MAX_JOB_ID_LENGTH:
        raise ValueError("公司ID过长，生成的 job_id 将超过 16 位限制")
    max_supported = (10**width) - 1
    required_max = start_index + len(rows) - 1
    if required_max > max_supported:
        raise ValueError(
            f"序号上限 {max_supported} 无法容纳 {required_max}，请调整 start-index 或缩小范围"
        )
    plan: List[Tuple[str, str]] = []
    for offset, row in enumerate(rows):
        current_id = str(row["id"])
        target_suffix = start_index + offset
        target_id = f"{prefix}{target_suffix:0{width}d}"
        if current_id != target_id:
            plan.append((current_id, target_id))
    return plan, width


def make_temp_id(sequence: int) -> str:
    return f"T{sequence:015d}"[:MAX_JOB_ID_LENGTH]


def summarize_plan(plan: Sequence[Tuple[str, str]], preview: int) -> str:
    if not plan:
        return ""
    sample = ", ".join(f"{old}->{new}" for old, new in plan[:preview])
    if len(plan) > preview:
        sample += ", ..."
    return sample


def apply_plan(
    db: Database,
    *,
    company_id: str,
    plan: Sequence[Tuple[str, str]],
    preview: int,
    dry_run: bool,
) -> None:
    if not plan:
        logging.info("公司 %s 的 job_id 已经连续，无需调整。", company_id)
        return
    logging.info(
        "公司 %s 计划更新 %s 条职位。预览：%s",
        company_id,
        len(plan),
        summarize_plan(plan, preview),
    )
    if dry_run:
        logging.info("DRY-RUN 模式启用，未写入数据库。")
        return
    temp_triplets: List[Tuple[str, str, str]] = []
    for idx, (old_id, new_id) in enumerate(plan, start=1):
        temp_triplets.append((old_id, make_temp_id(idx), new_id))
    connection = db._ensure_connection()
    try:
        with db.cursor() as cur:
            for old_id, temp_id, _ in temp_triplets:
                cur.execute("UPDATE job SET id=%s WHERE id=%s", (temp_id, old_id))
        with db.cursor() as cur:
            for _, temp_id, new_id in temp_triplets:
                cur.execute("UPDATE job SET id=%s WHERE id=%s", (new_id, temp_id))
        connection.commit()
    except Exception:
        logging.exception("公司 %s 重排失败，执行回滚。", company_id)
        connection.rollback()
        raise
    logging.info("公司 %s 重排完成，共更新 %s 条记录。", company_id, len(plan))


def backup_job_table(db: Database, backup_dir: str) -> Path:
    backup_path = Path(backup_dir)
    backup_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    table_suffix = uuid4().hex[:6]
    backup_table = f"job_backup_{timestamp}_{table_suffix}"
    statements = [
        f"CREATE TABLE `{backup_table}` LIKE `job`",
        f"INSERT INTO `{backup_table}` SELECT * FROM `job`",
    ]
    sql_file = backup_path / f"{backup_table}.sql"
    with sql_file.open("w", encoding="utf-8") as fp:
        fp.write(f"-- job 表备份生成于 {timestamp}\n")
        for stmt in statements:
            fp.write(f"{stmt};\n")
    with db.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)
    db._ensure_connection().commit()
    logging.info("已备份 job 表至 %s，并写入 SQL 文件 %s", backup_table, sql_file)
    return sql_file


def reorder_job_ids() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    settings = Settings.from_env(args.env_file)
    db = Database(settings)
    backup_job_table(db, args.backup_dir)
    category_ids = None
    if args.category_ids:
        category_ids = [cid.strip().upper() for cid in args.category_ids if cid and cid.strip()]
    try:
        company_ids = fetch_target_companies(db, args.company_ids)
        if not company_ids:
            logging.warning("未在 job 表找到 company_id，程序退出。")
            return 0
        for company_id in company_ids:
            rows = fetch_jobs(
                db,
                company_id=company_id,
                category_ids=category_ids,
                sort_by=args.sort_by,
                limit=args.limit,
            )
            if not rows:
                logging.info("公司 %s 没有满足条件的职位，跳过。", company_id)
                continue
            plan, width = build_plan(rows=rows, company_id=company_id, start_index=args.start_index)
            logging.debug(
                "公司 %s 检索 %s 条职位，按 %s 位序号重排。", company_id, len(rows), width
            )
            apply_plan(
                db,
                company_id=company_id,
                plan=plan,
                preview=args.preview,
                dry_run=args.dry_run,
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(reorder_job_ids())

