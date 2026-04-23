"""
拼多多招聘爬虫（careers.pddglobalhr.com）
支持校招(job_type=1)、实习(job_type=2)
"""

from global_main import fetch_with_retry, run_crawler
from global_db import save_to_database


# ---------- 配置 ----------
COMPANY_ID = "C008"
CAMPUS_LIST_URL = "https://careers.pddglobalhr.com/api/careers/api/recruit/position/list"
CAMPUS_BASE_URL = "https://careers.pddglobalhr.com/campus/grad/detail"
INTERN_LIST_URL = "https://careers.pddglobalhr.com/api/careers/api/recruit/position/train/list"
INTERN_BASE_URL = "https://careers.pddglobalhr.com/campus/intern/detail"
DETAIL_API_URL = "https://careers.pddglobalhr.com/api/careers/api/recruit/position/detail"
REQUEST_TIMEOUT = 10
RETRY_TIMES = 2

# 类型映射
JOB_TYPE_MAP = {
    1: {"list_api": CAMPUS_LIST_URL, "base_url": CAMPUS_BASE_URL},
    2: {"list_api": INTERN_LIST_URL, "base_url": INTERN_BASE_URL},
}


# ---------- 辅助函数 ----------
def extract_description_requirement(data: dict):
    description = (data.get("jobDuty") or "").strip()
    requirement = (data.get("serveRequirement") or "").strip()
    return description, requirement


def get_detail(post_id: str, location: str, job_url: str, job_type: int, fallback_job: dict = None) -> bool:
    """
    获取详情并入库（供 rewrite.py 直接调用）
    :param post_id:       职位ID
    :param location:      工作地点（可能为空）
    :param job_url:       职位详情页URL
    :param job_type:      招聘类型（1=校招，2=实习）
    :param fallback_job:  可选的列表数据字典，用于回退缺失字段
    :return:              是否成功入库
    """
    # 请求详情接口
    payload = {"id": post_id, "t": None}
    resp_json = fetch_with_retry("POST", DETAIL_API_URL, json=payload,
                                 timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
    data = resp_json.get("result") if resp_json else {}
    if not isinstance(data, dict):
        data = {}

    # 从详情提取
    title = (data.get("name") or "").strip()
    category = (data.get("jobName") or "").strip()
    description, requirement = extract_description_requirement(data)
    bonus = data.get("bonus") or ""
    final_location = data.get("workLocationName") or location

    # 从 fallback 列表数据回退
    if fallback_job and isinstance(fallback_job, dict):
        if not title:
            title = (fallback_job.get("name") or fallback_job.get("positionName") or "").strip()
        if not category:
            category = (fallback_job.get("jobName") or fallback_job.get("positionCategory") or "").strip()
        if not description:
            description = (fallback_job.get("jobDuty") or "").strip()
        if not requirement:
            requirement = (fallback_job.get("serveRequirement") or "").strip()
        if not final_location:
            final_location = (fallback_job.get("workLocationName") or fallback_job.get("workPlace") or "").strip()

    if not title:
        title = f"职位_{post_id}"
    if not category:
        category = "未分类"

    salary = ""
    education = ""
    publish_time = ""
    work_experience = ""

    try:
        save_to_database(
            status=0,
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
    """用户选择 1=校招，2=实习"""
    while True:
        try:
            choice = int(input("请选择招聘类型（1=校招，2=实习）: "))
            if choice in (1, 2):
                return choice
            print("请输入 1 或 2")
        except ValueError:
            print("输入无效，请输入数字 1 或 2")


def fetch_list_page(page: int, page_size: int, job_type: int):
    """根据 job_type 选择对应的列表接口"""
    cfg = JOB_TYPE_MAP.get(job_type)
    if not cfg:
        return [], 0
    payload = {"page": page, "pageSize": page_size, "t": None}
    resp = fetch_with_retry("POST", cfg["list_api"], json=payload,
                            timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
    if not resp:
        return [], 0
    result = resp.get("result") or resp.get("data") or {}
    jobs = result.get("list") or result.get("positionList") or []
    total = result.get("total") or result.get("count") or 0
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = 0
    return jobs, total


def process_job(job: dict, job_type: int) -> bool:
    """处理单个职位：调用 get_detail 入库，并传递列表数据作为 fallback"""
    pos_id = job.get("id") or job.get("positionId") or job.get("position_id")
    if not pos_id:
        return False

    cfg = JOB_TYPE_MAP.get(job_type)
    base_url = cfg["base_url"]
    job_url = f"{base_url}?positionId={pos_id}"

    # 提取 location（优先使用列表中的字段）
    location = job.get("workLocationName") or job.get("workPlace") or ""

    # 调用独立 get_detail，传入 fallback_job
    return get_detail(str(pos_id), location, job_url, job_type, fallback_job=job)


# ---------- 入口 ----------
def main():
    run_crawler(
        company_id=COMPANY_ID,
        get_job_type_func=get_job_type,
        fetch_list_page_func=fetch_list_page,
        process_job_func=process_job,
        base_delay=1.0
    )


if __name__ == "__main__":
    main()