"""
网易游戏（互娱）实习生招聘（campus.game.163.com）
只抓取实习生项目（projectIds=[30]），需要调详情接口获取描述和要求
"""

from global_main import fetch_with_retry, run_crawler, crawl_job_list_generic
from global_db import save_to_database

# ---------- 配置 ----------
COMPANY_ID = "C005"
LIST_API = "https://campus.game.163.com/api/recruitment/campus/position/list"
DETAIL_API = "https://campus.game.163.com/api/recruitment/campus/position/detail"
BASE_URL = "https://campus.game.163.com/position-detail"
REQUEST_TIMEOUT = 10
RETRY_TIMES = 2


# ---------- 辅助函数 ----------
def extract_description_requirement(data: dict):
    description = (data.get("positionDescription") or "").strip()
    requirement = (data.get("positionRequirement") or "").strip()
    return description, requirement


def extract_cities(data: dict) -> str:
    """从 workCities 列表中提取城市名拼接"""
    cities = data.get("workCities") or []
    if isinstance(cities, list):
        names = [c.get("cityName", "") for c in cities if isinstance(c, dict)]
        return "、".join(n for n in names if n)
    return str(cities) if cities else ""


# ---------- 核心函数：独立详情获取（供 rewrite.py 直接调用）----------
def get_detail(post_id: str, location: str, job_url: str, job_type: int, fallback_job: dict = None) -> bool:
    """
    获取职位详情并入库（可被 rewrite.py 复用）
    """
    # 1. 请求详情接口
    detail_data = {}
    status = 0
    if DETAIL_API:
        params = {"positionId": post_id}
        resp = fetch_with_retry("GET", DETAIL_API, params=params,
                                timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
        if resp and resp.get("status") == 1:
            detail_data = (resp.get("data") or {}).get("info") or {}

    # 2. 提取字段（优先详情，其次 fallback_job）
    title = detail_data.get("externalPositionName") or ""
    if not title and fallback_job:
        title = fallback_job.get("externalPositionName") or ""

    # category 使用 positionTypeAbbreviation（已是"父类-子类"格式）
    category = detail_data.get("positionTypeAbbreviation") or ""
    if not category and fallback_job:
        category = fallback_job.get("positionTypeAbbreviation") or ""

    description, requirement = extract_description_requirement(detail_data)
    if (not description or not requirement) and fallback_job:
        desc_fb, req_fb = extract_description_requirement(fallback_job)
        if not description:
            description = desc_fb
        if not requirement:
            requirement = req_fb

    bonus = ""
    work_experience = ""
    salary = None
    education = None
    publish_time = (fallback_job or {}).get("publishedAt") or None

    final_location = extract_cities(detail_data)
    if not final_location:
        final_location = extract_cities(fallback_job or {})

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
        "projectIds": [30],
        "positionTypeIds": [],
        "workplaceIds": [],
        "positionExternalTagIds": [],
        "attributeTypes": [],
        "pageNum": page,
        "pageSize": page_size
    }

    resp = fetch_with_retry("POST", LIST_API, json=payload,
                            timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
    if not resp:
        return [], 0

    data = resp.get("data") or {}
    jobs = data.get("list", [])
    total = data.get("count", 0)
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = 0
    return jobs, total


def process_job(job: dict, job_type: int) -> bool:
    """处理单个职位：调用 get_detail 入库"""
    post_id = job.get("positionId")
    if not post_id:
        print("跳过无效职位：缺少 positionId")
        return False

    location = extract_cities(job)
    job_url = f"{BASE_URL}/{post_id}"

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
