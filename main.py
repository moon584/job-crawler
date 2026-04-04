from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
import logging
from pathlib import Path
import sys
import time
from typing import List, Optional

from crawler.config import Settings
from crawler.db import Database
from crawler.http import HttpClient
from crawler.providers import load_provider
from crawler.rules import load_rule_file, apply_job_type_overrides
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
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="并发抓取的线程数 (默认 5)",
    )
    return parser.parse_args()


def prompt_company_id() -> str:
    while True:
        try:
            value = input("请输入公司ID（例如 C001）：").strip().upper()
            if value:
                return value
            print("公司ID不能为空，请重新输入。")
        except EOFError:
            print("C007")
            return "C007"


def prompt_job_type() -> int:
    message = "请输入 job_type（0=社会招聘，1=校园招聘）："
    while True:
        try:
            raw = input(message).strip()
            if raw in {"0", "1"}:
                return int(raw)
            print("输入无效，仅支持 0 或 1。")
        except EOFError:
            print("0")
            return 0


def resolve_crawl_mode_from_rule(rule) -> str:
    extra = getattr(rule, "extra", {}) or {}
    configured = extra.get("crawl_mode") if isinstance(extra, dict) else None
    if isinstance(configured, str):
        mode = configured.strip().lower()
        if mode in {"fast", "slow"}:
            logging.info("使用规则中的爬取模式：%s", mode)
            return mode
        logging.warning("规则中的 crawl_mode=%r 非法，默认回退为 fast 模式", configured)
    else:
        logging.info("规则中未配置 crawl_mode，默认使用 fast 模式")
    return "fast"


def prompt_category_ids() -> Optional[List[str]]:
    """询问用户要爬取的分类ID（中文注释）。"""
    while True:
        try:
            raw = input("请输入要爬取的category_id（多个用逗号分隔，输入 all 表示全部）：").strip()
            if not raw or raw.lower() == "all":
                return None
            candidates = [item.strip().upper() for item in raw.split(",") if item.strip()]
            if candidates:
                return candidates
            print("未输入有效的category_id，请重新输入。")
        except EOFError:
            print("all")
            return None


def prompt_post_limit() -> Optional[int]:
    """询问用户每个分类的抓取条数（中文注释）。"""
    while True:
        try:
            raw = input("请输入每个分类要爬取的条数（数字或 all 表示全部）：").strip().lower()
            if not raw or raw == "all":
                return None
            if raw.isdigit() and int(raw) > 0:
                return int(raw)
            print("请输入正整数或 all。")
        except EOFError:
            print("2")  # 仅抓取2条以便快速测试
            return 2


def setup_file_logging(company_id: str, job_type: int, crawl_mode: str) -> Path:
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"crawl_{company_id}_jt{job_type}_{crawl_mode}_{timestamp}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(file_handler)
    return log_file


def ask_user_yes_no(question: str, default: bool = False) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        try:
            choice = input(f"{question} {hint}: ").strip().lower()
            if not choice:
                return default
            if choice in ("y", "yes"):
                return True
            if choice in ("n", "no"):
                return False
            print("请输入 y 或 n。")
        except EOFError:
            return default


def handle_post_crawl_actions(database: Database, company_id: str, dry_run: bool) -> None:
    # 检查软删除
    with database.cursor() as cur:
        cur.execute("SELECT COUNT(*) as total FROM job WHERE is_deleted=1 AND company_id=%s", (company_id,))
        row = cur.fetchone()
        total_deleted = int(row["total"]) if row else 0

    if total_deleted > 0:
        print(f"\n======================================")
        print(f"【清理提示】公司 {company_id} 下，检测到 {total_deleted} 条过期岗位被标记为待删除 (is_deleted=1)。")
        if not dry_run:
            if ask_user_yes_no("是否现在从数据库中硬删除这些废弃岗位？", default=False):
                print(">>> 正在执行删除脚本...")
                subprocess.run([sys.executable, "tools/clean_deleted_jobs.py", "--company", company_id])
                print("<<< 删除结束。")
            else:
                print("已跳过硬删除。")
        else:
            print("(--dry-run 模式已跳过真实清理)")
    else:
        print(f"\n【清理提示】未检测到公司 {company_id} 有需要清理的待删除岗位。")

    # 询问重排
    print(f"\n======================================")
    print(f"【重排提示】是否需要对公司 {company_id} 的 job_id 进行连续重新编号？")
    if ask_user_yes_no("执行重新编号？", default=False):
        cmd = [sys.executable, "tools/rebuild_job_ids.py", "--company-id", company_id]
        if dry_run:
            cmd.append("--dry-run")
            print("(--dry-run 模式下将不会实际写入重排结果)")
        print(f">>> 正在执行: {' '.join(cmd)}")
        subprocess.run(cmd)
        print("<<< 重排结束。")
    else:
        print("已跳过重新编号。")


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stdout  # 确保 log 也能在控制台看到
    )
    settings = Settings.from_env(args.env_file)
    company_id = prompt_company_id()
    rule = load_rule_file(args.rules, company_id)
    job_type = prompt_job_type()
    rule = apply_job_type_overrides(rule, job_type)
    crawl_mode = resolve_crawl_mode_from_rule(rule)

    database = Database(settings)
    http_client = HttpClient(rule.throttle)
    provider_name = args.provider or rule.provider
    provider = load_provider(provider_name, rule, http_client=http_client)

    crawler = JobCrawler(
        database,
        http_client,
        provider,
        job_type=job_type,
        crawl_mode=crawl_mode,
        dry_run=args.dry_run,
        max_workers=args.workers,
    )
    category_ids = prompt_category_ids()
    post_limit = prompt_post_limit()

    # 建立日志文件应延后到所需变量已确定后
    log_file = setup_file_logging(company_id, job_type, crawl_mode)
    logging.info("日志文件已创建：%s", log_file)

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

        # 爬虫完成后询问并执行后续动作
        handle_post_crawl_actions(database, company_id, args.dry_run)

    except Exception:
        logging.exception("Crawler terminated with an error")
        sys.exit(1)
    finally:
        http_client.close()
        database.close()


if __name__ == "__main__":
    main()
