"""
腾讯校招/实习爬虫（join.qq.com）
列表同时包含校招和实习，根据 projectName 动态判断 job_type
"""

import time
from global_main import fetch_with_retry, get_user_pagination, random_delay, search_expired_job, get_max_items
from global_db import save_to_database
from datetime import datetime

# ---------- 配置 ----------
COMPANY_ID = "C001"
BASE_URL = "https://join.qq.com/post_detail.html"
LIST_API = "https://join.qq.com/api/v1/position/searchPosition"
DETAIL_API = "https://join.qq.com/api/v1/jobDetails/getJobDetailsByPostId"
REQUEST_TIMEOUT = 10
RETRY_TIMES = 2


# ---------- 辅助函数 ----------
def extract_description_requirement(data: dict):
    description = (data.get("desc") or "").strip()
    requirement = (data.get("request") or "").strip()
    if not description:
        description = (data.get("topicDetail") or "").strip()
    if not requirement:
        requirement = (data.get("topicRequirement") or "").strip()
    if not description or not requirement:
        dtos = data.get("subDirectionDtos")
        if isinstance(dtos, list) and dtos:
            first_dto = dtos[0] if isinstance(dtos[0], dict) else {}
            sub_dir = first_dto.get("subDirection") if isinstance(first_dto.get("subDirection"), dict) else {}
            if not description:
                description = sub_dir.get("desc", "").strip()
            if not requirement:
                requirement = sub_dir.get("request", "").strip()
    return description, requirement


def get_detail(post_id: str, location: str, job_url: str, detected_job_type: int) -> bool:
    """获取详情并入库，使用传入的 job_type"""
    timestamp = int(time.time() * 1000)
    detail_url = f"{DETAIL_API}?timestamp={timestamp}&postId={post_id}"
    data_json = fetch_with_retry("GET", detail_url, timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
    if not data_json:
        print(f"获取详情失败: {job_url}")
        return False

    data = data_json.get("data") or {}
    parent = data.get("tidName", "")
    child = data.get("title", "")
    category = f"{parent}-{child}" if parent or child else "未分类"
    title = child or parent or "无标题"
    description, requirement = extract_description_requirement(data)
    bonus = data.get("graduateBonus", "")
    salary = "面议"
    education = None
    publish_time = None
    work_experience = None
    status = data_json.get("status") or 0

    try:
        save_to_database(
            status=status,
            table_name="job",
            columns=["company_id", "job_type", "job_url", "post_id", "title",
                     "category", "description", "requirement", "bonus",
                     "location", "salary", "education", "publish_time", "work_experience"],
            data_tuple=(COMPANY_ID, detected_job_type, job_url, post_id, title,
                        category, description, requirement, bonus,
                        location, salary, education, publish_time, work_experience),
            unique_key="job_url"
        )
        return True
    except Exception as e:
        print(f"数据库保存失败 {job_url}: {e}")
        return False


# ---------- 自定义爬虫（不使用 run_crawler，因为 job_type 动态）----------
def get_job_type() -> int:
    """占位函数，实际不会用到，但为了兼容 run_crawler 可随便返回"""
    return 1  # 校招作为默认


def fetch_list_page(page: int, page_size: int, job_type: int):
    """获取列表页，忽略 job_type 参数"""
    timestamp = int(time.time() * 1000)
    list_url = f"{LIST_API}?timestamp={timestamp}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "projectIdList": [], "projectMappingIdList": [], "keyword": "",
        "bgList": [], "workCountryType": 0, "workCityList": [],
        "recruitCityList": [], "positionFidList": [],
        "pageIndex": page, "pageSize": page_size,
    }
    resp = fetch_with_retry("POST", list_url, json=payload, headers=headers,
                            timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
    if not resp:
        return [], 0
    data = resp.get("data") or {}
    jobs = data.get("positionList", [])
    total = data.get("count", 0)
    return jobs, total


def process_job(job: dict, _job_type: int) -> bool:
    """动态检测职位类型（校招=1，实习=2）并入库"""
    post_id = job.get("postId")
    if not post_id:
        return False

    location = job.get("workCities", "")
    job_url = f"{BASE_URL}?postId={post_id}"
    project_name = job.get("projectName", "")
    detected_type = 2 if ("实习" in project_name) else 1
    return get_detail(post_id, location, job_url, detected_type)


def main():
    # 由于 job_type 动态，无法使用 run_crawler 的自动过期检查，需要自己实现完整流程
    start_page, page_size = get_user_pagination()
    max_items = get_max_items()
    start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    current_page = start_page
    total_count = 0
    success_count = 0
    completed = False

    while True:
        jobs, total_count = fetch_list_page(current_page, page_size, 0)
        if not jobs:
            break
        for job in jobs:
            if process_job(job, 0):
                success_count += 1
                if max_items > 0 and success_count >= max_items:
                    break
        print(f"已获取第 {current_page} 页，本页 {len(jobs)} 条，累计成功 {success_count} / {total_count} 条")
        if max_items > 0 and success_count >= max_items:
            print(f"已达到最大爬取条数限制（{max_items}条），停止")
            break
        if current_page * page_size >= total_count:
            completed = True
            break
        current_page += 1
        random_delay(base=1.0, extra=1.5)

    print(f"抓取完成，成功保存 {success_count} 个职位，总记录数 {total_count}")
    if completed and total_count > 0:
        # 动态检测可能产生两种 job_type：校招(1)和实习(2)，都需要做过期检查
        search_expired_job(COMPANY_ID, 1, start_time)
        search_expired_job(COMPANY_ID, 2, start_time)


if __name__ == "__main__":
    main()