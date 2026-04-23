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


# ---------- 标准接口函数 ----------
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
    """处理单个职位：获取详情并入库"""
    post_id = job.get("PostId")
    if not post_id:
        return False

    # 构建列表页提供的 URL（备用）
    job_url = job.get("PostURL") or f"{BASE_URL}?postId={post_id}"
    location = job.get("LocationName", "")

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
    # 优先使用详情返回的 URL
    final_job_url = data.get("PostURL") or job_url

    salary = None
    education = None

    try:
        save_to_database(
            status=0,
            table_name="job",
            columns=["company_id", "job_type", "job_url", "post_id", "title",
                     "category", "description", "requirement", "bonus",
                     "location", "salary", "education", "publish_time", "work_experience"],
            data_tuple=(COMPANY_ID, job_type, final_job_url, post_id, title,
                        category, description, requirement, bonus,
                        location, salary, education, publish_time, work_experience),
            unique_key="job_url"
        )
        return True
    except Exception as e:
        print(f"写库失败 {final_job_url}: {e}")
        return False


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