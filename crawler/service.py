from __future__ import annotations

from collections import defaultdict
import concurrent.futures
from datetime import datetime, timezone
import logging
import os
import threading
import time
import sys
from typing import Dict, List, Optional

from .db import Database
from .http import HttpClient
from .models import CategoryMapping, CrawlStats, JobRecord
from .providers.base import BaseProvider
from .utils import normalize_category_id


class JobCrawler:
    """通用抓取调度器，具体字段映射由 provider 决定。"""

    def __init__(
        self,
        db: Database,
        http_client: HttpClient,
        provider: BaseProvider,
        job_type: int,
        *,
        crawl_mode: str = "fast",  # Deprecated parameter, kept for compatibility
        dry_run: bool = False,
        max_workers: int = 5,
    ) -> None:
        self._db = db
        self._http = http_client
        self._provider = provider
        self._job_type = job_type
        if hasattr(self._provider, "set_job_type"):
            self._provider.set_job_type(self._job_type)
        self._max_workers = max_workers
        self._dry_run = dry_run
        extra_cfg = getattr(provider, "extra", {}) or {}
        raw_skip = extra_cfg.get("skip_detail_if_exists") if isinstance(extra_cfg, dict) else None
        self._skip_detail_if_exists = raw_skip if isinstance(raw_skip, bool) else True
        self._stats: Optional[CrawlStats] = None
        self._warmup_done = False
        self._quit_requested = False
        self._quit_listener_thread: Optional[threading.Thread] = None
        self._quit_listener_shutdown = threading.Event()

    def _process_single_post(
        self,
        post: Dict[str, object],
        category_id: str,
    ) -> None:
        if self._check_quit_requested():
            return
        stats = self._stats
        if not stats:
            return

        existing_job_url = self._find_existing_job_url_by_post(post)
        if existing_job_url:
            self._touch_existing_job(existing_job_url)
            stats.record_skip_existing()
            return
        post_id = self._provider.extract_post_id(post)
        if not post_id:
            stats.record_failure()
            logging.warning("跳过缺少PostId的岗位：%s", post)
            self._persist_failed_job_from_post(category_id, post)
            return
        try:
            detail = self._fetch_detail(post_id)
            record = self._build_job_record(category_id, detail)
            inserted = self._persist_record(record)
            if inserted:
                stats.record_success()
            else:
                self._touch_existing_job(record.job_url)
                stats.record_skip_existing()
        except Exception:
            stats.record_failure()
            logging.exception("抓取岗位 %s 失败", post_id)
            self._persist_failed_job_from_post(category_id, post)

    def run(
        self,
        target_categories: Optional[List[str]] = None,
        post_limit: Optional[int] = None,
    ) -> CrawlStats:
        """执行统一爬取模式（基于心跳刷新机制）。"""
        self._start_quit_listener()
        self._crawl_start_time = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            if self._provider.supports_auto_category():
                if target_categories:
                    logging.info("自动分类模式会忽略手动指定的分类：%s", ", ".join(target_categories))
                return self._run_auto_category(post_limit)
            stats = CrawlStats()
            self._stats = stats
            category_mappings = self._resolve_category_mappings(target_categories)
            if not category_mappings:
                logging.warning("指定的分类未找到或没有可爬取的叶子节点")
                return stats
            for mapping in category_mappings:
                list_failed = False
                if self._check_quit_requested():
                    break
                api_category_id = mapping.api_category_id or ""
                logging.info(
                    "开始抓取分类 %s（接口ID=%s，条数限制=%s）",
                    mapping.db_category_id,
                    mapping.api_category_id or "-",
                    post_limit or "all",
                )
                official_total: Optional[int] = None
                try:
                    previous_list_failures = stats.list_failures
                    posts = self._fetch_posts(api_category_id, post_limit)
                    list_failed = stats.list_failures > previous_list_failures
                    official_total = len(posts)
                    stats.record_category(mapping.db_category_id, official_total)

                    with concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                        futures = [
                            executor.submit(self._process_single_post, post, mapping.db_category_id)
                            for post in posts
                        ]
                        for future in concurrent.futures.as_completed(futures):
                            if self._check_quit_requested():
                                executor.shutdown(wait=False, cancel_futures=True)
                                break
                            try:
                                future.result()
                            except Exception:
                                logging.exception("任务执行过程中发生未捕获异常")
                finally:
                    self._finalize_category(mapping.db_category_id, list_failed, post_limit)
                    self._refresh_category_counts(mapping.db_category_id, official_total)
            logging.info(
                "分类抓取完成：共处理%s条，成功%s条，失败%s条，跳过%s条",
                stats.total_posts,
                stats.success,
                stats.failed,
                stats.skipped_existing,
            )
            logging.info("各分类抓取数量：%s", stats.per_category)
            logging.info(
                "HTTP 请求统计：列表失败 %s 次，详情失败 %s 次",
                stats.list_failures,
                stats.detail_failures,
            )
            return stats
        finally:
            self._stop_quit_listener()

    def _process_auto_post(
        self,
        post: Dict[str, object],
        default_category_id: str,
        known_category_ids: set[str],
        category_totals: Dict[str, int],
        category_hit_stats: Dict[str, int],
        totals_lock: threading.Lock,
    ) -> None:
        if self._check_quit_requested():
            return
        stats = self._stats
        if not stats:
            return

        existing_job_url = self._find_existing_job_url_by_post(post)
        if existing_job_url:
            self._touch_existing_job(existing_job_url)
            stats.record_skip_existing()
            return
        post_id = self._provider.extract_post_id(post)
        if not post_id:
            stats.record_failure()
            logging.warning("跳过缺少PostId的岗位：%s", post)
            self._persist_failed_job_from_post(default_category_id, post)
            return
        try:
            detail = self._fetch_detail(post_id)
        except Exception:
            stats.record_failure()
            logging.exception("岗位 %s 详情请求失败", post_id)
            self._persist_failed_job_from_post(default_category_id, post)
            return
        resolved_category = self._provider.resolve_category_id(post, detail)

        with totals_lock:
            if resolved_category:
                target_category = resolved_category
            else:
                target_category = default_category_id
                category_hit_stats["_default_hits"] += 1
            category_hit_stats[target_category] += 1

            if target_category not in known_category_ids:
                category_hit_stats["_unknown_hits"] += 1
                logging.warning(
                    "岗位 %s 映射到未知分类 %s，已跳过；请确保数据库存在该分类", post_id, target_category
                )
                stats.record_failure()
                return

        try:
            record = self._build_job_record(target_category, detail)
            inserted = self._persist_record(record)
            if inserted:
                with totals_lock:
                    category_totals[target_category] += 1
                stats.record_category(target_category, 1)
                stats.record_success()
            else:
                self._touch_existing_job(record.job_url)
                stats.record_skip_existing()
        except Exception:
            stats.record_failure()
            logging.exception("写入岗位 %s 失败", post_id)
            self._persist_failed_job_from_post(target_category, post)

    def _run_auto_category(self, post_limit: Optional[int]) -> CrawlStats:
        stats = CrawlStats()
        self._stats = stats
        extra_cfg = getattr(self._provider, "extra", {}) or {}
        default_mapping = self._build_default_mapping(extra_cfg)
        if not default_mapping:
            raise ValueError("自动分类模式需要在规则中配置 default_category_id 与 default_api_category_id")
        default_category_id = default_mapping.db_category_id
        if not default_category_id:
            raise ValueError("自动分类模式缺少 default_category_id 配置")
        required_category_ids = self._collect_auto_category_ids(
            extra_cfg,
            self._provider.company_id,
            default_category_id,
        )
        created = self._db.ensure_categories_exist(self._provider.company_id, required_category_ids)
        if created:
            logging.info("自动补齐缺失分类：%s", ", ".join(created))
        base_api_category = default_mapping.api_category_id or ""
        logging.info(
            "自动分类模式：使用 API 分类 %s 请求列表接口（limit=%s）",
            default_mapping.api_category_id or "-",
            post_limit or "all",
        )
        known_category_ids = self._db.fetch_category_ids(self._provider.company_id)
        if default_category_id not in known_category_ids:
            raise ValueError(
                "自动分类模式要求数据库已存在 default_category_id=%s 的分类记录" % default_category_id
            )
        list_failed = False
        previous_list_failures = stats.list_failures
        try:
            posts = self._fetch_posts(base_api_category, post_limit)
        except Exception:
            logging.exception("获取全量列表失败")
            posts = []
        list_failed = stats.list_failures > previous_list_failures
        logging.info("全量列表抓取完成，共 %s 条", len(posts))
        category_totals: Dict[str, int] = defaultdict(int)
        category_hit_stats: Dict[str, int] = defaultdict(int)
        totals_lock = threading.Lock()

        with concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = [
                executor.submit(
                    self._process_auto_post,
                    post,
                    default_category_id,
                    known_category_ids,
                    category_totals,
                    category_hit_stats,
                    totals_lock,
                )
                for post in posts
            ]
            for future in concurrent.futures.as_completed(futures):
                if self._check_quit_requested():
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    future.result()
                except Exception:
                    logging.exception("任务执行过程中发生未捕获异常")

        self._finalize_company(list_failed, post_limit)
        for category_id in known_category_ids:
            # Refresh counts for all known categories (or only those affected)
            self._refresh_category_counts(category_id, official_total=category_totals.get(category_id))
        logging.info(
            "自动分类模式完成：共处理 %s 条岗位，成功 %s 条，失败 %s 条",
            stats.total_posts,
            stats.success,
            stats.failed,
        )
        default_hits = category_hit_stats.pop("_default_hits", 0)
        unknown_hits = category_hit_stats.pop("_unknown_hits", 0)
        logging.info(
            "自动分类命中统计：%s（默认分类命中=%s，未知分类命中=%s）",
            dict(sorted(category_hit_stats.items())),
            default_hits,
            unknown_hits,
        )
        logging.info("各分类抓取数量：%s", stats.per_category)
        logging.info(
            "HTTP 请求统计：列表失败 %s 次，详情失败 %s 次",
            stats.list_failures,
            stats.detail_failures,
        )
        return stats

    @staticmethod
    def _collect_auto_category_ids(
        extra_cfg: Dict[str, object], company_id: str, default_category_id: str
    ) -> List[str]:
        category_ids = [default_category_id]
        category_rules = extra_cfg.get("category_rules")
        if isinstance(category_rules, list):
            for item in category_rules:
                if not isinstance(item, dict):
                    continue
                candidate = str(item.get("category_id", "")).strip()
                if not candidate:
                    continue
                if not candidate.startswith(company_id):
                    logging.warning(
                        "自动分类规则 category_id=%s 不属于公司 %s，已忽略",
                        candidate,
                        company_id,
                    )
                    continue
                if candidate:
                    category_ids.append(candidate)
        return category_ids

    def _resolve_category_mappings(
        self, target_categories: Optional[List[str]]
    ) -> List[CategoryMapping]:
        extra_cfg = getattr(self._provider, "extra", {}) or {}
        mappings = self._db.fetch_category_mappings(
            self._provider.company_id,
            category_ids=target_categories,
            only_leaf=(target_categories is None),
        )
        if not mappings:
            fallback = self._build_default_mapping(extra_cfg)
            if fallback:
                logging.info(
                    "数据库分类表为空，使用默认分类 %s（API=%s）",
                    fallback.db_category_id,
                    fallback.api_category_id or "-",
                )
                mappings = [fallback]
        if not mappings and not target_categories:
            return []
        if target_categories:
            normalized_targets = {cid.upper(): cid for cid in target_categories}
            requested = set(normalized_targets.keys())
            available = {mapping.db_category_id.upper() for mapping in mappings}
            missing = sorted(requested - available)
            if missing:
                fallback_mappings: List[CategoryMapping] = []
                for cid in missing:
                    original_id = normalized_targets.get(cid, cid)
                    fallback = self._build_default_mapping(extra_cfg, db_category_id=original_id)
                    if fallback:
                        fallback_mappings.append(fallback)
                if fallback_mappings:
                    mappings.extend(fallback_mappings)
                    logging.info(
                        "以下分类未在数据库找到，回退到默认 API 分类 %s：%s",
                        fallback_mappings[0].api_category_id or "-",
                        ", ".join(mapping.db_category_id for mapping in fallback_mappings),
                    )
                fallback_ids = {mapping.db_category_id.upper() for mapping in fallback_mappings}
                unresolved = [cid for cid in missing if cid not in fallback_ids]
                if unresolved:
                    raise ValueError(
                        "数据库中找不到以下 category_id，且未配置默认分类：%s"
                        % ", ".join(normalized_targets.get(cid, cid) for cid in unresolved)
                    )
        return mappings

    def _build_default_mapping(
        self, extra_cfg: Dict[str, object], *, db_category_id: Optional[str] = None
    ) -> Optional[CategoryMapping]:
        db_id_source: Optional[str]
        if db_category_id is None:
            raw_default = extra_cfg.get("default_category_id")
            db_id_source = raw_default if isinstance(raw_default, str) else None
        else:
            db_id_source = db_category_id
        if not db_id_source:
            return None
        api_candidate = extra_cfg.get("default_api_category_id")
        api_id: Optional[str]
        if isinstance(api_candidate, str) and api_candidate:
            normalized_candidate = api_candidate.strip()
            try:
                api_id = normalize_category_id(normalized_candidate)
            except ValueError as exc:
                logging.error(
                    "公司 %s 的 default_api_category_id='%s' 非法：%s",
                    self._provider.company_id,
                    api_candidate,
                    exc,
                )
                return None
        elif db_category_id is not None:
            logging.warning(
                "公司 %s 未配置 default_api_category_id，无法为缺失的分类 %s 使用默认 API 分类",
                self._provider.company_id,
                db_id_source,
            )
            return None
        else:
            api_id = None
        return CategoryMapping(
            db_category_id=db_id_source,
            api_category_id=api_id,
            crawled_job_count=0,
            official_job_count=-1,
        )

    def _fetch_posts(self, category_id: str, post_limit: Optional[int]) -> List[Dict[str, object]]:
        self._run_warmup_once()
        posts: List[Dict[str, object]] = []
        page = 1
        while True:
            if self._check_quit_requested():
                break
            try:
                list_result = self._provider.fetch_posts(category_id, page)
            except Exception:
                logging.exception("分类 %s 第%s页列表接口请求失败", category_id or "-", page)
                if self._stats:
                    self._stats.record_list_failure()
                break
            posts.extend(list_result.posts)
            logging.info(
                "分类 %s 第%s页抓取完成，本页%s条，总计%s/%s",
                category_id,
                page,
                len(list_result.posts),
                len(posts),
                list_result.total_count,
            )
            if post_limit and len(posts) >= post_limit:
                posts = posts[:post_limit]
                break
            if self._check_quit_requested():
                break
            if not list_result.has_more:
                break
            page += 1
        return posts

    def _start_quit_listener(self) -> None:
        self._quit_requested = False
        self._quit_listener_shutdown.clear()
        if os.name != "nt":
            return
        if not hasattr(sys.stdin, "isatty") or not sys.stdin.isatty():
            return
        if self._quit_listener_thread and self._quit_listener_thread.is_alive():
            return
        self._quit_listener_thread = threading.Thread(target=self._listen_quit_key_windows, daemon=True)
        self._quit_listener_thread.start()
        logging.info("爬取中可按 q 提前退出并直接结算当前结果。")

    def _stop_quit_listener(self) -> None:
        self._quit_listener_shutdown.set()
        if self._quit_listener_thread and self._quit_listener_thread.is_alive():
            self._quit_listener_thread.join(timeout=0.3)
        self._quit_listener_thread = None

    def _listen_quit_key_windows(self) -> None:
        try:
            import msvcrt  # type: ignore
        except Exception:
            return
        while not self._quit_listener_shutdown.is_set():
            try:
                if msvcrt.kbhit():
                    key = msvcrt.getwch()
                    if key and key.lower() == "q":
                        self._quit_requested = True
                        logging.warning("检测到 q，准备提前结束本轮爬取并结算。")
                        break
            except Exception:
                break
            time.sleep(0.05)

    def _check_quit_requested(self) -> bool:
        return self._quit_requested

    def _run_warmup_once(self) -> None:
        if self._warmup_done:
            return
        provider_warmup = getattr(self._provider, "warmup_urls", None)
        warmup_urls = provider_warmup() if callable(provider_warmup) else []
        if not warmup_urls:
            self._warmup_done = True
            return
        provider_headers = getattr(self._provider, "warmup_headers", None)
        headers = provider_headers() if callable(provider_headers) else None
        for url in warmup_urls:
            try:
                logging.info("预热会话：%s", url)
                self._http.warmup(url, headers=headers)
            except Exception:
                logging.warning("会话预热失败，继续尝试抓取：%s", url, exc_info=True)
        self._warmup_done = True

    def _fetch_detail(self, post_id: str) -> Dict[str, object]:
        try:
            return self._provider.fetch_detail(post_id)
        except Exception:
            if self._stats:
                self._stats.record_detail_failure()
            raise

    def _find_existing_job_url_by_post(self, post: Dict[str, object]) -> Optional[str]:
        if not self._skip_detail_if_exists:
            return None
        predictor = getattr(self._provider, "predict_job_url", None)
        if not callable(predictor):
            return None
        job_url = predictor(post)
        if not job_url:
            return None
        existing = self._db.fetch_job_by_url(job_url)
        if not existing:
            return None
        # 不论快爬还是慢爬，如果在列表里命中了，就将其 is_deleted 重置为 0，因为官网还有。
        self._touch_existing_job(job_url)
        logging.info("列表命中已存在职位，详情前跳过：%s", job_url)
        return job_url

    def _finalize_category(self, category_id: str, list_failed: bool, post_limit: Optional[int]) -> None:
        if self._dry_run:
            logging.info("[DRY-RUN] 收尾跳过分类 %s 的下架软删阶段", category_id)
            return
        if list_failed:
            logging.warning("分类 %s (job_type=%s) 列表请求异常，不执行下架数据软删", category_id, self._job_type)
            return
        if post_limit is not None:
            logging.info("分类 %s (job_type=%s) 存在 post_limit=%s，不执行下架数据软删", category_id, self._job_type, post_limit)
            return

        affected = self._db.soft_delete_unseen_jobs_by_category(
            self._provider.company_id, category_id, self._job_type, self._crawl_start_time
        )
        if affected > 0:
            logging.info("【注意】分类 %s (job_type=%s) 已将 %s 条下架职位标记为待删除。如需彻底删除，请运行清理脚本。", category_id, self._job_type, affected)


    def _finalize_company(self, list_failed: bool, post_limit: Optional[int]) -> None:
        if self._dry_run:
            logging.info("[DRY-RUN] 收尾跳过公司 %s 的下架软删阶段", self._provider.company_id)
            return
        if list_failed:
            logging.warning(
                "公司 %s (job_type=%s) 列表请求异常，不执行下架数据软删",
                self._provider.company_id,
                self._job_type,
            )
            return
        if post_limit is not None:
            logging.info(
                "公司 %s (job_type=%s) 存在 post_limit=%s，不执行下架数据软删",
                self._provider.company_id,
                self._job_type,
                post_limit,
            )
            return

        affected = self._db.soft_delete_unseen_jobs_by_company(
            self._provider.company_id, self._job_type, self._crawl_start_time
        )
        if affected > 0:
            logging.info("【注意】公司 %s (job_type=%s) 已将 %s 条下架职位标记为待删除。如需彻底删除，请运行清理脚本。", self._provider.company_id, self._job_type, affected)


    def _touch_existing_job(self, job_url: str) -> None:
        if self._dry_run:
            return
        touched = self._db.touch_job_alive_by_url(job_url, self._job_type)
        if not touched:
            logging.debug("未找到可复活的已存在岗位：%s", job_url)

    def _build_job_record(self, category_id: str, detail: Dict[str, object]) -> JobRecord:
        from datetime import timezone
        crawled_at = datetime.now(timezone.utc).replace(tzinfo=None)
        record = self._provider.build_job_record(category_id, detail, crawled_at=crawled_at)
        record.job_type = self._job_type
        return record

    def _persist_record(self, record: JobRecord) -> bool:
        if self._dry_run:
            logging.info("[DRY-RUN] Would upsert job: %s", record.job_url)
            return True
        existing = self._db.fetch_job_by_url(record.job_url)
        if existing:
            existing_status = self._normalize_crawl_status(existing.get("crawl_status"))
            existing_id = existing.get("id")
            if not existing_id:
                logging.warning("命中无ID的历史记录，无法更新，跳过：%s", record.job_url)
                return False

            changes = self._compute_changes(existing, record)

            if not changes and existing_status == 1:
                # 没有任何实质内容改变，且之前也是成功的
                self._touch_existing_job(record.job_url)
                logging.info("职位内容无变化，按 job_url 跳过：%s", record.job_url)
                return False

            # 有变化，或者之前是失败的，需要更新
            changes["crawl_status"] = 1
            changes["is_deleted"] = 0
            changes["crawled_at"] = record.crawled_at
            self._db.update_job(str(existing_id), changes)

            if existing_status == 0:
                logging.info("修复失败的历史职位：%s", record.job_url)
            else:
                # 过滤掉辅助字段打印，只看业务字段
                changed_keys = [k for k in changes.keys() if k not in ("crawl_status", "is_deleted", "crawled_at")]
                logging.info("更新职位信息（有字段变化）：%s -> 变化字段: %s", record.job_url, changed_keys)
            return True

        record.is_deleted = 0
        record.id = self._db.generate_next_job_id(self._provider.company_id)
        record.created_at = record.crawled_at
        self._db.insert_job(record.as_sql_params())
        logging.info("新增职位 %s", record.id)
        return True

    def _persist_failed_job_from_post(self, category_id: str, post: Dict[str, object]) -> None:
        if self._dry_run:
            return
        predictor = getattr(self._provider, "predict_job_url", None)
        if not callable(predictor):
            return
        job_url = predictor(post)
        if not job_url:
            return
        self._persist_failed_job(category_id, str(job_url).strip())

    def _persist_failed_job(self, category_id: str, job_url: str) -> None:
        if self._dry_run or not job_url:
            return
        existing = self._db.fetch_job_by_url(job_url)
        from datetime import timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if existing:
            existing_id = existing.get("id")
            existing_status = self._normalize_crawl_status(existing.get("crawl_status"))
            if existing_status == 1:
                return
            if not existing_id:
                return
            self._db.update_job(
                str(existing_id),
                {
                    "category_id": category_id,
                    "job_type": self._job_type,
                    "crawl_status": 0,
                    "is_deleted": 0,
                    "crawled_at": now,
                },
            )
            logging.info("更新失败占位职位（crawl_status=0）：%s", job_url)
            return
        placeholder = JobRecord(
            id=self._db.generate_next_job_id(self._provider.company_id),
            company_id=self._provider.company_id,
            category_id=category_id,
            job_url=job_url,
            title="抓取失败占位",
            salary="面议",
            job_type=self._job_type,
            education=None,
            publish_time=None,
            location=None,
            description="",
            requirement=None,
            bonus=None,
            work_experience=None,
            is_deleted=0,
            crawl_status=0,
            crawled_at=now,
            created_at=now,
        )
        self._db.insert_job(placeholder.as_sql_params())
        logging.info("写入失败占位职位（crawl_status=0）：%s", job_url)

    @staticmethod
    def _normalize_crawl_status(raw_status: object) -> int:
        try:
            return int(raw_status) if raw_status is not None else 0
        except (TypeError, ValueError):
            return 0

    def _compute_changes(self, existing: Dict[str, object], record: JobRecord) -> Dict[str, object]:
        new_values = record.as_sql_params()
        comparable_fields = [
            "title",
            "category_id",
            "salary",
            "job_type",
            "education",
            "publish_time",
            "location",
            "description",
            "requirement",
            "bonus",
            "work_experience",
        ]
        changes: Dict[str, object] = {}
        for field in comparable_fields:
            if existing.get(field) != new_values[field]:
                changes[field] = new_values[field]
        # 移除在这里强行添加 crawled_at 的行为，交由外部判断
        return changes

    def _should_skip_category(self, mapping: CategoryMapping) -> bool:
        crawled = mapping.crawled_job_count
        official = mapping.official_job_count
        if official >= 0 and crawled == official:
            logging.info(
                "分类 %s 的岗位数量已与官网一致（%s 条），跳过本轮抓取。",
                mapping.db_category_id,
                official,
            )
            return True
        if official >= 0:
            logging.info(
                "分类 %s 数量不一致：已爬 %s 条，官网 %s 条，继续抓取。",
                mapping.db_category_id,
                crawled,
                official,
            )
        else:
            logging.info(
                "分类 %s 未配置官网数量，默认执行抓取。",
                mapping.db_category_id,
            )
        return False

    def _refresh_category_counts(self, category_id: str, official_total: Optional[int] = None) -> None:
        if self._dry_run:
            logging.debug("[DRY-RUN] 不更新分类 %s 的岗位数量统计", category_id)
            return
        try:
            crawled_total = self._db.sync_category_counts(category_id, official_total)
        except Exception:
            logging.exception("刷新分类 %s 的岗位数量失败", category_id)
            return
        if official_total is None:
            logging.info("分类 %s 的爬取职位数量更新为 %s（官网总数保持不变）", category_id, crawled_total)
        else:
            logging.info(
                "分类 %s 的岗位数量已更新完成：官网=%s，已录入=%s",
                category_id,
                official_total,
                crawled_total,
            )

    def _handle_category_gap(self, category_id: str, official_total: int) -> None:
        pass  # Deprecated
