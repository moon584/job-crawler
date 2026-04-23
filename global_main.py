"""
global_main.py
通用爬虫辅助函数 + 标准爬虫流程
"""

import time
import random
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, Callable

import requests
from global_db import search_expired_job   # 统一过期检查


# ---------- 原有函数（保持不变）----------
def fetch_with_retry(method: str, url: str, retry_times: int = 2, timeout: int = 10, **kwargs) -> Optional[Dict]:
    """带重试的 HTTP 请求，返回 JSON 字典，失败返回 None。"""
    for attempt in range(retry_times):
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"请求失败 (尝试 {attempt+1}/{retry_times}): {url}, 错误: {e}")
            if attempt == retry_times - 1:
                return None
            time.sleep(1 * (attempt + 1))
    return None


def safe_get(data: Dict, *keys, default: str = "") -> str:
    """安全地从嵌套字典中取值，支持多级 key。"""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key, default)
        else:
            return default
    return data if data is not None else default


def get_user_pagination(default_start: int = 1, default_size: int = 20) -> Tuple[int, int]:
    """获取用户输入的起始页码和每页条数，带校验和默认值"""
    try:
        start_page = int(input(f"请输入起始页码（默认{default_start}）: ") or str(default_start))
        page_size = int(input(f"请输入每页条数（默认{default_size}）: ") or str(default_size))
        if start_page < 1 or page_size < 1:
            raise ValueError
        return start_page, page_size
    except ValueError:
        print(f"输入无效，使用默认值：起始页={default_start}，每页{default_size}条")
        return default_start, default_size


def random_delay(base: float = 1.0, extra: float = 1.5) -> None:
    """随机休眠 base 到 base+extra 秒，避免反爬"""
    time.sleep(random.uniform(base, base + extra))


# ---------- 新增通用爬虫流程 ----------
def crawl_job_list_generic(
    job_type: int,
    start_page: int,
    page_size: int,
    fetch_list_page_func: Callable[[int, int, int], Tuple[list, int]],
    process_job_func: Callable[[dict, int], bool],
    base_delay: float = 1.0
) -> Tuple[int, int]:
    """
    通用分页爬取逻辑
    :param job_type:            招聘类型（由各爬虫定义）
    :param start_page:          起始页码
    :param page_size:           每页条数
    :param fetch_list_page_func: 函数 (page, page_size, job_type) -> (jobs_list, total_count)
    :param process_job_func:     函数 (job_item, job_type) -> bool（是否成功入库）
    :param base_delay:           基础延迟秒数
    :return: (成功保存数, 总记录数)
    """
    current_page = start_page
    total_count = 0
    success_count = 0

    while True:
        jobs, total_count = fetch_list_page_func(current_page, page_size, job_type)
        if not jobs:
            print(f"第 {current_page} 页无数据，停止")
            break

        for job in jobs:
            if process_job_func(job, job_type):
                success_count += 1

        print(f"已获取第 {current_page} 页，本页 {len(jobs)} 条，累计成功 {success_count} / {total_count} 条")

        if current_page * page_size >= total_count:
            print("已到达最后一页")
            break

        current_page += 1
        random_delay(base=base_delay, extra=1.5)

    return success_count, total_count


def run_crawler(
    company_id: str,
    get_job_type_func: Callable[[], int],
    fetch_list_page_func: Callable[[int, int, int], Tuple[list, int]],
    process_job_func: Callable[[dict, int], bool],
    base_delay: float = 1.0
) -> None:
    """
    标准爬虫入口，包含用户输入、分页爬取、过期检查
    :param company_id:           公司ID（用于过期检查）
    :param get_job_type_func:    无参函数，返回 job_type
    :param fetch_list_page_func: 同 crawl_job_list_generic
    :param process_job_func:     同 crawl_job_list_generic
    :param base_delay:           基础延迟秒数
    """
    start_page, page_size = get_user_pagination()
    job_type = get_job_type_func()
    start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    saved, total = crawl_job_list_generic(
        job_type, start_page, page_size,
        fetch_list_page_func, process_job_func,
        base_delay
    )

    print(f"抓取完成，成功保存 {saved} 个职位，总记录数 {total}")
    if saved == total and total > 0:
        search_expired_job(company_id, job_type, start_time)
    else:
        print("未完整抓取全量数据，跳过过期检查")