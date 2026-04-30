"""
网易游戏（雷火）实习生招聘（xiaozhao.leihuo.netease.com）
只抓取实习生项目（project_id=73），列表接口已含全部字段，无需详情接口
"""

from global_main import fetch_with_retry, run_crawler, crawl_job_list_generic
from global_db import save_to_database

# ---------- 配置 ----------
COMPANY_ID = "C005"
LIST_API = "https://xiaozhao.leihuo.netease.com/api/apply/job/list/show"
DETAIL_API = ""  # 列表已有全部信息，无需详情接口
BASE_URL = "https://campus.163.com/app/detail/index"
REQUEST_TIMEOUT = 10
RETRY_TIMES = 2


# ---------- 辅助函数 ----------
def extract_description_requirement(data: dict):
    description = (data.get("job_description") or "").strip()
    requirement = (data.get("job_requirement") or "").strip()
    return description, requirement


# ---------- 核心函数：独立详情获取（供 rewrite.py 直接调用）----------
def get_detail(post_id: str, location: str, job_url: str, job_type: int, fallback_job: dict = None) -> bool:
    """
    获取职位详情并入库（无详情接口，仅从 fallback_job 提取）
    """
    status = 0

    # 全部从 fallback_job 提取
    title = (fallback_job or {}).get("job_name") or ""
    category = (fallback_job or {}).get("category_name") or ""
    description, requirement = extract_description_requirement(fallback_job or {})
    bonus = ""
    work_experience = ""
    salary = None
    education = None
    publish_time = None

    final_location = location
    if not final_location and fallback_job:
        final_location = (fallback_job.get("work_place_name") or "").strip()

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
    """获取列表页数据（GET 请求，参数在 query string 中）"""
    params = {
        "job_name": "",
        "page_size": page_size,
        "page_number": page,
        "project_id": 73
    }

    resp = fetch_with_retry("GET", LIST_API, params=params,
                            timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
    if not resp:
        return [], 0

    data = resp.get("data") or {}
    jobs = data.get("apply_job_list", [])
    total = data.get("count_number", 0)
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = 0
    return jobs, total


def process_job(job: dict, job_type: int) -> bool:
    """处理单个职位"""
    post_id = job.get("ehr_job_id")
    if not post_id:
        print("跳过无效职位：缺少 ehr_job_id")
        return False

    location = (job.get("work_place_name") or "").strip()
    project_id = job.get("ehr_project_id", "73")
    job_url = f"{BASE_URL}?id={post_id}&projectId={project_id}&channel=TAUScgyo"

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
