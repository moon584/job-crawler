"""
腾讯官方招聘爬虫（careers.tencent.com）
固定抓取社招职位
"""

import time
from global_main import fetch_with_retry, run_crawler
from global_db import save_to_database

# ---------- 配置 ----------
COMPANY_ID = "C001"
LIST_API = "https://careers.tencent.com/tencentcareer/api/post/Query"
DETAIL_API = "https://careers.tencent.com/tencentcareer/api/post/ByPostId"
BASE_URL = "https://careers.tencent.com/jobdesc.html"
REQUEST_TIMEOUT = 10
RETRY_TIMES = 2


# ---------- 辅助函数 ----------
def extract_description_requirement(data: dict):
    description = (data.get("Responsibility") or "").strip()
    requirement = (data.get("Requirement") or "").strip()
    return description, requirement


def get_category_from_term(term: str, father: str) -> str:
    term_map = {
        "40001001": "技术研发", "40001002": "质量管理", "40001003": "技术运营",
        "40001004": "安全技术", "40001005": "AI、算法与大数据", "40001006": "企管",
        "40002001": "产品", "40002002": "游戏产品", "40002003": "项目", "40002004": "金融",
        "40003001": "设计", "40003002": "游戏美术",
        "40004": "营销与公关",
        "40005001": "销售", "40005002": "客服",
        "40006": "内容", "40007": "财务", "40008": "人力资源",
        "40009": "法律与公共策略", "40010": "行政支持", "40011": "战略与投资",
    }
    child = term_map.get(str(term), "")
    if father and child:
        return f"{father}-{child}"
    return father or child or "未分类"


# ---------- 核心函数：独立详情获取（供 rewrite.py 直接调用）----------
def get_detail(post_id: str, location: str, job_url: str, job_type: int, fallback_job: dict = None) -> bool:
    """
    获取职位详情并入库
    :param post_id:       职位ID (PostId)
    :param location:      工作地点（可能为空）
    :param job_url:       职位详情页 URL（列表页提供的，可能被详情接口返回的替换）
    :param job_type:      招聘类型（此接口固定为 0）
    :param fallback_job:  可选的列表数据字典，用于回填 location 等字段（本接口暂不需要）
    :return:              是否成功入库
    """
    # 请求详情
    timestamp = int(time.time() * 1000)
    params = {"timestamp": timestamp, "postId": post_id, "language": "zh-cn"}
    detail_json = fetch_with_retry("GET", DETAIL_API, params=params,
                                   timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
    if not detail_json or detail_json.get("Code") != 200:
        print(f"详情请求失败: {job_url}")
        return False

    data = detail_json.get("Data") or {}
    father = data.get("CategoryName", "")
    term = data.get("OuterPostTypeID", "")
    category = get_category_from_term(term, father)
    title = data.get("RecruitPostName", "") or "无标题"
    description, requirement = extract_description_requirement(data)
    bonus = data.get("ImportantItem", "")
    work_experience = data.get("RequireWorkYearsName", "")
    publish_time = data.get("LastUpdateTime", "")

    # 如果详情中没有 location，且传入了 fallback_job，尝试从中获取
    final_location = location
    if not final_location and fallback_job:
        final_location = fallback_job.get("LocationName", "")

    salary = None
    education = None
    status=0

    try:
        save_to_database(
            status=status,
            table_name="job",
            columns=["company_id", "job_type", "job_url", "post_id", "title",
                     "category", "description", "requirement", "bonus",
                     "location", "salary", "education", "publish_time", "work_experience"],
            data_tuple=(COMPANY_ID, job_type, job_url, post_id, title,
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
    """此接口仅社招，固定返回 0"""
    return 0


def fetch_list_page(page: int, page_size: int, job_type: int):
    """获取列表页"""
    timestamp = int(time.time() * 1000)
    params = {
        "timestamp": timestamp, "countryId": "", "cityId": "", "bgIds": "",
        "productId": "", "categoryId": "", "parentCategoryId": "", "attrId": 1,
        "keyword": "", "pageIndex": page, "pageSize": page_size,
        "language": "zh-cn", "area": "cn",
    }
    resp = fetch_with_retry("GET", LIST_API, params=params,
                            timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
    if not resp:
        return [], 0
    data_obj = resp.get("Data") or {}
    jobs = data_obj.get("Posts", [])
    total = data_obj.get("Count", 0)
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = 0
    return jobs, total


def process_job(job: dict, job_type: int) -> bool:
    """处理单个职位：调用 get_detail 入库"""
    post_id = job.get("PostId")
    if not post_id:
        return False

    # 从列表数据中提取字段
    job_url = job.get("PostURL") or f"{BASE_URL}?postId={post_id}"
    location = job.get("LocationName", "")

    # 调用独立 get_detail，传入列表数据作为 fallback
    return get_detail(str(post_id), location, job_url, job_type, fallback_job=job)


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