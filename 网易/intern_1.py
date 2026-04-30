"""
网易主站实习生招聘（hr.163.com）
只抓取实习岗位（workType=1），列表接口已含全部字段，无需详情接口
"""

from datetime import datetime
from global_main import fetch_with_retry, run_crawler, crawl_job_list_generic
from global_db import save_to_database

# ---------- 配置 ----------
COMPANY_ID = "C005"
LIST_API = "https://hr.163.com/api/hr163/position/queryPage"
DETAIL_API = ""  # 列表已有全部信息，无需详情接口
BASE_URL = "https://hr.163.com/job-detail.html"
REQUEST_TIMEOUT = 10
RETRY_TIMES = 2


# ---------- 辅助函数 ----------
def extract_description_requirement(data: dict):
    description = (data.get("description") or "").strip()
    requirement = (data.get("requirement") or "").strip()
    return description, requirement


def ts_to_datetime(ts_ms: int) -> str:
    """毫秒时间戳 -> 可读日期时间字符串"""
    if not ts_ms:
        return ""
    try:
        return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError, TypeError):
        return ""


# ---------- 核心函数：独立详情获取（供 rewrite.py 直接调用）----------
def get_detail(post_id: str, location: str, job_url: str, job_type: int, fallback_job: dict = None) -> bool:
    """
    获取职位详情并入库（无详情接口，仅从 fallback_job 提取）
    """
    detail_data = {}

    # 2. 提取字段（全部从 fallback_job 获取，因为无详情接口）
    title = (fallback_job or {}).get("name") or ""
    category = (fallback_job or {}).get("firstPostTypeName") or ""
    description, requirement = extract_description_requirement(fallback_job or {})
    bonus = ""
    work_experience = (fallback_job or {}).get("reqWorkYearsName") or ""
    salary = None
    education = (fallback_job or {}).get("reqEducationName") or None
    publish_time = ts_to_datetime((fallback_job or {}).get("updateTime"))
    final_location = location
    if not final_location and fallback_job:
        loc_list = fallback_job.get("workPlaceNameList") or []
        final_location = "、".join(loc_list) if isinstance(loc_list, list) else str(loc_list)

    status = 0

    if not title:
        title = f"职位_{post_id}"
    if not category:
        category = "未分类"

    # 3. 入库
    try:
        save_to_database(
            status=status,
            table_name="job",
            columns=["company_id", "job_type", "job_url", "post_id", "title",
                     "category", "description", "requirement", "bonus",
                     "location", "salary", "education", "publish_time", "work_experience"],
            data_tuple=(COMPANY_ID, job_type, job_url, str(post_id), title,
                        category, description, requirement, bonus,
                        final_location, salary, education, publish_time, work_experience),
            unique_key="job_url"
        )
        return True
    except Exception as e:
        print(f"写库失败 {job_url}: {e}")
        return False


# ---------- 标准接口函数（供 run_crawler 使用）----------
def get_job_type() -> int:
    """固定实习，无需用户选择"""
    return 2


def fetch_list_page(page: int, page_size: int, job_type: int):
    """获取列表页数据"""
    payload = {
        "currentPage": page,
        "pageSize": page_size,
        "workType": "1"  # 固定实习
    }

    resp = fetch_with_retry("POST", LIST_API, json=payload,
                            timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
    if not resp:
        return [], 0

    data = resp.get("data") or {}
    jobs = data.get("list", [])
    total = data.get("total", 0)
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = 0
    return jobs, total


def process_job(job: dict, job_type: int) -> bool:
    """处理单个职位"""
    post_id = job.get("id")
    if not post_id:
        print("跳过无效职位：缺少 id")
        return False

    loc_list = job.get("workPlaceNameList") or []
    location = "、".join(loc_list) if isinstance(loc_list, list) else str(loc_list)
    job_url = f"{BASE_URL}?id={post_id}&lang=zh"

    return get_detail(str(post_id), location, job_url, job_type, fallback_job=job)


# ---------- 独立爬取函数（供统一入口调用，不做出检查）----------
def run_crawl(start_page: int, page_size: int, max_items: int):
    """执行爬取，不做过期检查。返回 (成功数, 获取总数, 是否完整爬完)"""
    return crawl_job_list_generic(
        job_type=2,
        start_page=start_page,
        page_size=page_size,
        fetch_list_page_func=fetch_list_page,
        process_job_func=process_job,
        base_delay=1.0,
        max_items=max_items
    )


# ---------- 入口 ----------
def main():
    from global_main import get_user_pagination, get_max_items
    start_page, page_size = get_user_pagination()
    max_items = get_max_items()
    saved, fetched, completed = run_crawl(start_page, page_size, max_items)
    print(f"抓取完成，成功保存 {saved} 个职位，共抓取 {fetched} 个职位")


if __name__ == "__main__":
    main()
