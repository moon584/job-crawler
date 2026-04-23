"""
{公司名称}招聘爬虫模板
支持招聘类型：{0=社招, 1=校招, 2=实习 等，根据实际调整}
"""

from global_main import fetch_with_retry, run_crawler
from global_db import save_to_database

# ---------- 配置 ----------
COMPANY_ID = "CXXX"                     # 公司唯一标识，需与数据库一致
LIST_API = "https://xxx.com/api/list"   # 列表接口 URL
DETAIL_API = "https://xxx.com/api/detail"  # 详情接口 URL（可选）
BASE_URL = "https://xxx.com/job/detail"    # 职位详情页基础 URL
REQUEST_TIMEOUT = 10                    # 请求超时（秒）
RETRY_TIMES = 2                         # 重试次数

# 可选：类型映射，例如用户输入 0/1/2 映射到接口参数
# JOB_TYPE_MAP = {0: {...}, 1: {...}, 2: {...}}

# 可选：请求头（如需）
# HEADERS = {"Content-Type": "application/json"}


# ---------- 辅助函数（按需添加）----------
def extract_description_requirement(data: dict):
    """从详情数据中提取职位描述和要求"""
    description = (data.get("jobDuty") or "").strip()
    requirement = (data.get("jobRequirement") or "").strip()
    return description, requirement


# ---------- 核心函数：独立详情获取（供 rewrite.py 直接调用）----------
def get_detail(post_id: str, location: str, job_url: str, job_type: int, fallback_job: dict = None) -> bool:
    """
    获取职位详情并入库（可被 rewrite.py 复用）
    :param post_id:       职位唯一标识
    :param location:      工作地点（可能为空）
    :param job_url:       职位详情页 URL
    :param job_type:      招聘类型（0/1/2 等）
    :param fallback_job:  可选的列表数据字典，用于回填缺失字段（当详情接口字段不全时使用）
    :return:              是否成功入库
    """
    # 1. 请求详情接口（如果提供了 DETAIL_API）
    detail_data = {}
    if DETAIL_API:
        # 根据接口类型构造请求（示例为 GET，参数为 id）
        params = {"id": post_id}
        resp = fetch_with_retry("GET", DETAIL_API, params=params,
                                timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
        if resp:
            detail_data = resp.get("data") or {}

    # 2. 提取字段（优先详情，其次 fallback_job）
    title = detail_data.get("title") or ""
    if not title and fallback_job:
        title = fallback_job.get("title") or ""

    category = detail_data.get("category") or ""
    if not category and fallback_job:
        category = fallback_job.get("category") or ""

    description, requirement = extract_description_requirement(detail_data)
    if (not description or not requirement) and fallback_job:
        desc_fb, req_fb = extract_description_requirement(fallback_job)
        if not description:
            description = desc_fb
        if not requirement:
            requirement = req_fb

    bonus = detail_data.get("bonus") or ""
    if not bonus and fallback_job:
        bonus = fallback_job.get("bonus", "")

    work_experience = detail_data.get("workYear") or ""
    if not work_experience and fallback_job:
        work_experience = fallback_job.get("workYear", "")

    salary = detail_data.get("salary") or None
    if not salary and fallback_job:
        salary = fallback_job.get("salary")

    education = detail_data.get("education") or None
    if not education and fallback_job:
        education = fallback_job.get("education")

    publish_time = detail_data.get("publishTime") or None
    if not publish_time and fallback_job:
        publish_time = fallback_job.get("publishTime")

    final_location = detail_data.get("location") or location
    if not final_location and fallback_job:
        final_location = fallback_job.get("location", "")

    # 默认值处理
    if not title:
        title = f"职位_{post_id}"
    if not category:
        category = "未分类"

    # 3. 入库
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
    """
    获取用户选择的招聘类型，返回 int 类型的 job_type。
    如果该爬虫只抓取一种类型，可直接返回固定值（如 0），无需用户输入。
    """
    while True:
        try:
            choice = int(input("请选择招聘类型（0=社招，1=校招，2=实习）: "))
            if choice in (0, 1, 2):
                return choice
            print("请输入 0、1 或 2")
        except ValueError:
            print("输入无效，请输入数字 0、1 或 2")


def fetch_list_page(page: int, page_size: int, job_type: int):
    """
    获取列表页数据。
    :param page:       当前页码（从 start_page 开始递增）
    :param page_size:  每页条数
    :param job_type:   招聘类型（由 get_job_type 返回）
    :return:           (jobs_list, total_count)
                       jobs_list 为列表，每个元素是一个职位字典（需包含唯一标识字段）
                       total_count 为总记录数（整数）
    """
    # 构造请求参数（示例：POST JSON）
    payload = {
        "pageNo": page,
        "pageSize": page_size,
        # 其他参数，如 job_type 映射等
    }
    # 可选：根据 job_type 调整 payload
    # if job_type == 1:
    #     payload["type"] = "campus"

    resp = fetch_with_retry("POST", LIST_API, json=payload,
                            timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
    if not resp:
        return [], 0

    # 根据实际接口响应结构提取 jobs 和 total
    data = resp.get("data") or {}
    jobs = data.get("list", [])          # 职位列表
    total = data.get("total", 0)         # 总记录数
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = 0
    return jobs, total


def process_job(job: dict, job_type: int) -> bool:
    """
    处理单个职位：调用 get_detail 入库。
    :param job:        列表中的职位字典（至少包含唯一标识字段，如 post_id）
    :param job_type:   招聘类型
    :return:           是否成功保存（True/False）
    """
    # 1. 提取必要字段
    post_id = job.get("postId") or job.get("id")
    if not post_id:
        print("跳过无效职位：缺少唯一标识")
        return False

    location = job.get("city", "") or job.get("location", "")
    job_url = f"{BASE_URL}?id={post_id}"

    # 2. 调用独立 get_detail，传入列表数据作为 fallback
    return get_detail(str(post_id), location, job_url, job_type, fallback_job=job)


# ---------- 入口 ----------
def main():
    run_crawler(
        company_id=COMPANY_ID,
        get_job_type_func=get_job_type,
        fetch_list_page_func=fetch_list_page,
        process_job_func=process_job,
        base_delay=1.0      # 请求间隔基础秒数
    )


if __name__ == "__main__":
    main()