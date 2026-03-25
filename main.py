from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import List, Optional

from crawler.config import Settings
from crawler.db import Database
from crawler.http import HttpClient
from crawler.providers import load_provider
from crawler.rules import load_rule_file
from crawler.service import JobCrawler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tencent careers crawler")
    parser.add_argument("--rules", default="rules/company.json", help="Path to company rule file")
    parser.add_argument("--env-file", default=None, help="Optional path to .env file")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to the database")
    parser.add_argument(
        "--provider",
        default=None,
        help="官网适配器名称（默认读取规则文件中的 provider 字段）",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Log verbosity",
    )
    return parser.parse_args()


def prompt_company_id() -> str:
    while True:
        value = input("请输入公司ID（例如 C001）：").strip().upper()
        if value:
            return value
        print("公司ID不能为空，请重新输入。")


def prompt_job_type() -> int:
    message = "请输入 job_type（0=社会招聘，1=校园招聘）："
    while True:
        raw = input(message).strip()
        if raw in {"0", "1"}:
            return int(raw)
        print("输入无效，仅支持 0 或 1。")


def prompt_category_ids() -> Optional[List[str]]:
    """询问用户要爬取的分类ID（中文注释）。"""
    while True:
        raw = input("请输入要爬取的category_id（多个用逗号分隔，输入 all 表示全部）：").strip()
        if not raw or raw.lower() == "all":
            return None
        candidates = [item.strip().upper() for item in raw.split(",") if item.strip()]
        if candidates:
            return candidates
        print("未输入有效的category_id，请重新输入。")


def prompt_post_limit() -> Optional[int]:
    """询问用户每个分类的抓取条数（中文注释）。"""
    while True:
        raw = input("请输入每个分类要爬取的条数（数字或 all 表示全部）：").strip().lower()
        if not raw or raw == "all":
            return None
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("请输入正整数或 all。")


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    settings = Settings.from_env(args.env_file)
    company_id = prompt_company_id()
    rule = load_rule_file(args.rules, company_id)
    database = Database(settings)
    http_client = HttpClient(rule.throttle)
    provider_name = args.provider or rule.provider
    provider = load_provider(provider_name, rule)
    job_type = prompt_job_type()
    crawler = JobCrawler(
        database,
        http_client,
        provider,
        job_type=job_type,
        dry_run=args.dry_run,
    )
    category_ids = prompt_category_ids()
    post_limit = prompt_post_limit()
    try:
        start_time = time.perf_counter()
        stats = crawler.run(target_categories=category_ids, post_limit=post_limit)
        duration = time.perf_counter() - start_time
        logging.info(
            "本次爬取完成：共处理 %s 条岗位，其中成功 %s 条、失败 %s 条，跳过 %s 条，耗时 %.2f 秒",
            stats.total_posts,
            stats.success,
            stats.failed,
            stats.skipped_existing,
            duration,
        )
    except Exception:
        logging.exception("Crawler terminated with an error")
        sys.exit(1)
    finally:
        http_client.close()
        database.close()


if __name__ == "__main__":
    main()
