"""
美团招聘爬虫
支持社招(job_type=0)、校招(job_type=1)、实习(job_type=2)
"""
from global_main import fetch_with_retry, run_crawler, safe_get
from global_db import save_to_database

# ---------- 配置 ----------
COMPANY_ID = "C007"
LIST_API = "https://zhaopin.meituan.com/api/official/job/getJobList"
DETAIL_API = "https://zhaopin.meituan.com/api/official/job/getJobDetail"
BASE_URL = "https://zhaopin.meituan.com/web/position/detail"
HEADERS = {"Content-Type": "application/json"}
REQUEST_TIMEOUT = 10
RETRY_TIMES = 2

# 类型映射：用户输入 -> 接口参数 & URL后缀
JOB_TYPE_MAP = {
    0: {"jobType": [{"code": "3", "subCode": []}], "url_suffix": "social"},
    1: {"jobType": [{"code": "1", "subCode": []}], "url_suffix": "campus"},
    2: {"jobType": [{"code": "2", "subCode": []}], "url_suffix": "campus"},
}


# ---------- 辅助函数 ----------
def extract_description_requirement(data: dict):
    description = (data.get("jobDuty") or "").strip()
    requirement = (data.get("jobRequirement") or "").strip()
    return description, requirement


# ---------- 核心函数：独立详情获取（供 rewrite.py 直接调用）----------
def get_detail(post_id: str, location: str, job_url: str, job_type: int, fallback_job: dict = None) -> bool:
    """
    获取职位详情并入库
    :param post_id:       职位ID (jobUnionId)
    :param location:      工作地点（可能为空）
    :param job_url:       职位详情页 URL
    :param job_type:      招聘类型 (0/1/2)
    :param fallback_job:  可选的列表数据字典（美团列表数据字段较少，暂未使用）
    :return:              是否成功入库
    """
    # 请求详情
    detail_payload = {"jobUnionId": post_id, "jobShareType": "1"}
    detail_json = fetch_with_retry("POST", DETAIL_API, json=detail_payload, headers=HEADERS,
                                   timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
    if not detail_json:
        print(f"详情请求失败: {job_url}")
        return False

    data = detail_json.get("data") or {}
    father = data.get("jobFamily", "")
    child = data.get("jobFamilyGroup", "")
    category = f"{father}-{child}" if father or child else "未分类"
    title = data.get("name", "") or "无标题"
    description, requirement = extract_description_requirement(data)
    bonus = data.get("precedence", "")
    work_experience = data.get("workYear") or ""
    status = 0

    # 以下字段 API 未提供
    salary = None
    education = None
    publish_time = None

    # 如果传入了 fallback_job，可尝试从中补充字段（美团列表数据通常不需要）
    if fallback_job and isinstance(fallback_job, dict):
        if not location:
            city_list = fallback_job.get("cityList")
            if isinstance(city_list, list) and city_list:
                first = city_list[0]
                if isinstance(first, dict):
                    location = first.get("name") or ""
                elif isinstance(first, str):
                    location = first
            elif isinstance(city_list, str):
                location = city_list

    try:
        save_to_database(
            status=status,
            table_name="job",
            columns=["company_id", "job_type", "job_url", "post_id", "title",
                     "category", "description", "requirement", "bonus",
                     "location", "salary", "education", "publish_time", "work_experience"],
            data_tuple=(COMPANY_ID, job_type, job_url, post_id, title,
                        category, description, requirement, bonus,
                        location, salary, education, publish_time, work_experience),
            unique_key="job_url"
        )
        return True
    except Exception as e:
        print(f"写库失败 {job_url}: {e}")
        return False


# ---------- 标准接口函数（供 run_crawler 使用）----------
def get_job_type() -> int:
    """让用户选择招聘类型，返回 0/1/2"""
    while True:
        try:
            choice = int(input("请输入招聘类型（0=社招，1=校招，2=实习）: "))
            if choice in (0, 1, 2):
                return choice
            print("请输入 0、1 或 2")
        except ValueError:
            print("输入无效，请输入数字 0、1 或 2")


def fetch_list_page(page: int, page_size: int, job_type: int):
    """
    获取列表页数据
    返回: (jobs_list, total_count)
    """
    type_cfg = JOB_TYPE_MAP.get(job_type)
    if not type_cfg:
        print(f"无效的 job_type: {job_type}")
        return [], 0

    payload = {
        "page": {"pageNo": page, "pageSize": page_size},
        "jobShareType": "1",
        "keywords": "",
        "cityList": [],
        "department": [],
        "jfJgList": [],
        "jobType": type_cfg["jobType"],
        "typeCode": [],
        "specialCode": [],
        "u_query_id": "",
        "r_query_id": ""
    }

    resp = fetch_with_retry("POST", LIST_API, json=payload, headers=HEADERS,
                            timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
    if not resp:
        return [], 0

    data_obj = resp.get("data") or {}
    jobs = data_obj.get("list", [])
    page_info = data_obj.get("page") or {}
    total = page_info.get("totalCount", 0)
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = 0
    return jobs, total


def process_job(job: dict, job_type: int) -> bool:
    """处理单个职位：调用 get_detail 入库"""
    post_id = job.get("jobUnionId")
    if not post_id:
        print("跳过无效职位：jobUnionId 为空")
        return False

    # 提取 location（从列表数据）
    city_list = job.get("cityList")
    location = ""
    if isinstance(city_list, list) and city_list:
        first = city_list[0]
        if isinstance(first, dict):
            location = first.get("name") or ""
        elif isinstance(first, str):
            location = first
    elif isinstance(city_list, str):
        location = city_list

    url_suffix = JOB_TYPE_MAP[job_type]["url_suffix"]
    job_url = f"{BASE_URL}?jobUnionId={post_id}&highlightType={url_suffix}"

    # 调用独立 get_detail，传入列表数据作为 fallback
    return get_detail(post_id, location, job_url, job_type, fallback_job=job)


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