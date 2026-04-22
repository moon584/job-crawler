import requests
import time
from db import save_to_database, search_expired_job
from datetime import datetime
# 拼多多（校招）爬虫脚本
# - 列表接口返回在 result.list
# - 详情接口返回在 result 下（或直接为对象），描述字段为 jobDuty，任职要求为 serveRequirement
# - 职位类别没有子类，直接使用 jobName 作为 category

company_id = "C008"
list_url = "https://careers.pddglobalhr.com/api/careers/api/recruit/position/list"
detail_url = "https://careers.pddglobalhr.com/api/careers/api/recruit/position/detail"
base_url = "https://careers.pddglobalhr.com/campus/grad/detail"

intern_list_url = "https://careers.pddglobalhr.com/api/careers/api/recruit/position/train/list"
intern_base_url = "https://careers.pddglobalhr.com/campus/intern/detail"

all_jobs = []
total=0

def extract_description_requirement(result, fallback=None):
    """
    从详情或列表项中提取 description 与 requirement：
    - 优先使用 result 中的 jobDuty / serveRequirement 字段
    返回 (description, requirement)
    """
    fallback = fallback or {}
    description = (result.get("jobDuty") or fallback.get("jobDuty") or "").strip()
    requirement = (result.get("serveRequirement") or "").strip()
    return description, requirement


def get_detail(job_type, position_id, job_url, job_from_list=None):
    """
    请求详情并解析需要写入数据库的字段；若详情请求失败，尝试使用列表数据回退。
    返回 True/False 表示是否成功处理（不会对失败进行重试，调用方可决定）。
    """
    try:
        resp = requests.post(detail_url, json={"id": position_id, "t": None}, timeout=10)
        resp.raise_for_status()
        body = resp.json() or {}
    except Exception as e:
        print(f"详情请求失败 id={position_id}: {e}")
        body = {}

    # 兼容不同返回格式：优先取 result
    result = body.get("result") or body.get("data") or body
    if not isinstance(result, dict):
        result = {}

    title = (result.get("name") or result.get("title") or (job_from_list or {}).get("name") or "").strip()
    # 拼多多没有子类，直接使用 jobName
    category = (result.get("jobName") or (job_from_list or {}).get("jobName") or "").strip()
    description, requirement = extract_description_requirement(result, fallback=job_from_list)
    bonus = result.get("bonus") or ""
    location = result.get("workLocationName") or result.get("workLocation") or (job_from_list or {}).get("workLocationName") or ""
    try:
        save_to_database(
            table_name="job",
            columns=["company_id", "job_type", "title", "category", "description", "requirement", "bonus", "location", "job_url"],
            data_tuple=(company_id, job_type, title, category, description, requirement, bonus, location, job_url),
            unique_key="job_url"
        )
    except Exception as e:
        print(f"写库失败 {job_url}: {e}")
        return False

    return True


def get_joblist(job_type, page, pagesize):
    """
    分页抓取职位列表并逐条调用 get_detail 写库。
    注意 total 可能为字符串，需转换为 int；若解析失败，使用列表长度停止。
    """
    global all_jobs, total
    while True:
        payload = {"page": page, "pageSize": pagesize, "t": None}
        try:
            resp = requests.post(list_url, json=payload, timeout=10)
            resp.raise_for_status()
            body = resp.json() or {}
        except Exception as e:
            print(f"列表请求失败 page={page}: {e}")
            break

        result = body.get("result") or body.get("data") or {}
        if not isinstance(result, dict):
            result = {}

        jobs = result.get("list") or result.get("positionList") or []
        # total 可能为字符串或数字
        total = result.get("total") or result.get("count") or 0

        if not jobs:
            print("本页无数据，停止")
            break

        for job in jobs:
            pos_id = job.get("id") or job.get("positionId") or job.get("positionId")
            if not pos_id:
                # 拼多多 id 字段可能为字符串形式
                pos_id = job.get("positionId") or job.get("position_id")
            if not pos_id:
                print("跳过无 id 的职位")
                continue

            job_url = f"{base_url}?positionId={pos_id}"
            # 先尝试详情接口，若失败则使用列表项作为回退
            get_detail(job_type, pos_id, job_url, job_from_list=job)
        all_jobs.extend(jobs)
        print(f"已获取第 {page} 页，本页 {len(jobs)} 条，累计 {len(all_jobs)} / {total} 条")

        # 判断是否结束：若 total 已知且 page*pagesize >= total 则结束；否则继续
        if total and page * pagesize >= total:
            print("已获取全部职位")
            break

        page += 1
        time.sleep(0.5)

    print(f"最终共获取 {len(all_jobs)} 个职位")

def get_intern_list(page, pagesize):
    global all_jobs, total
    current_page = page
    while True:
        payload = {"page": current_page, "pageSize": pagesize, "t": None}
        try:
            resp = requests.post(intern_list_url, json=payload, timeout=10)
            resp.raise_for_status()
            body = resp.json() or {}
        except Exception as e:
            print(f"实习列表请求失败 page={current_page}: {e}")
            break

        result = body.get("result") or body.get("data") or {}
        if not isinstance(result, dict):
            result = {}

        jobs = result.get("list") or result.get("positionList") or []
        total = result.get("total") or result.get("count") or 0
        if not jobs:
            print("本页无数据（实习），停止")
            break

        for job in jobs:
            pos_id = job.get("id") or job.get("positionId") or job.get("position_id")
            if not pos_id:
                print("跳过无 id 的实习职位")
                continue

            job_url = f"{intern_base_url}?positionId={pos_id}"
            # 实习使用 job_type = 2
            try:
                get_detail(job_type, pos_id, job_url, job_from_list=job)
            except Exception as e:
                print(f"处理实习职位失败 id={pos_id}: {e}")
                continue

        all_jobs.extend(jobs)
        print(f"已获取实习第 {current_page} 页，本页 {len(jobs)} 条，累计 {len(all_jobs)} / {total} 条")

        if total and current_page * pagesize >= total:
            print("已获取全部实习岗位")
            break

        current_page += 1
        time.sleep(0.5)

    print(f"实习最终共获取 {len(all_jobs)} 个职位")

if __name__ == "__main__":
    start_page = int(input("请输入起始页码:"))
    page_size = int(input("请输入每页条数:"))
    start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    while True:
        job_type = int(input("请选择要运行的招聘类型(1=校招，2=实习):"))
        if job_type == 1:
            # 校招，job_type = 1
            get_joblist(job_type, start_page, page_size)
            break
        elif job_type == 2:
            # 实习，使用专门的实习列表接口与 job_type = 2
            get_intern_list(start_page, page_size)
            break
        else:
            print("输入无效，请输入数字 1（校招）或 2（实习）。")
    if len(all_jobs)==total:
        search_expired_job(company_id, job_type, start_time)
