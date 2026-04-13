import requests
import time
import json
from db import save_to_database

url = "https://join.qq.com/api/v1/position/searchPosition"
detail_url = "https://join.qq.com/api/v1/jobDetails/getJobDetailsByPostId"
base_url = "https://join.qq.com/post_detail.html"

def extract_description_requirement(data):
    """提取职位描述与要求，优先使用常规字段，空值时回退。"""
    description = (data.get("desc") or "").strip()
    requirement = (data.get("request") or "").strip()

    if not description:
        description = (data.get("topicDetail") or "").strip()
        if not description:
            # subDirectionDtos 是一个列表，取第一个元素中的 subDirection 字典
            dtos = data.get("subDirectionDtos")
            if isinstance(dtos, list) and dtos:
                first_dto = dtos[0]
                sub_dir = first_dto.get("subDirection") if isinstance(first_dto, dict) else None
                if isinstance(sub_dir, dict):
                    description = sub_dir.get("desc", "").strip()

    if not requirement:
        requirement = (data.get("topicRequirement") or "").strip()
        if not requirement:
            dtos = data.get("subDirectionDtos")
            if isinstance(dtos, list) and dtos:
                first_dto = dtos[0]
                sub_dir = first_dto.get("subDirection") if isinstance(first_dto, dict) else None
                if isinstance(sub_dir, dict):
                    requirement = sub_dir.get("request", "").strip()

    return description, requirement

def get_detail(company_id,job_type,post_id,location,job_url):
    timestamp = int(time.time() * 1000)
    try:
        resp = requests.get(
            f"{detail_url}?timestamp={timestamp}&postId={post_id}",
            timeout=10
        )
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        father = data.get("tidName", "")
        child = data.get("title", "")
        category = f"{father}-{child}"
        title = child
        description, requirement = extract_description_requirement(data)
        bonus = data.get("graduateBonus", "")

        salary = ""
        education = ""
        publish_time = ""
        work_experience=""

    except Exception as e:
        print(f"爬取失败 job_url={job_url}: {e}")
        return False  # 不保存失败记录

    save_to_database(
        table_name="job",
        columns=["company_id","job_type","title", "category", "description", "requirement", "bonus","location","job_url"],
        data_tuple=(company_id, job_type,title, category, description, requirement, bonus,location, job_url),
        unique_key="job_url"
    )
    return True

def get_joblist(company_id,job_type,page,pagesize):
    headers = {
        "Content-Type": "application/json"
    }
    all_jobs = []
    crawl_ok = True
    while True:
        timestamp = int(time.time() * 1000)
        payload = {
            "projectIdList": [],
            "projectMappingIdList": [],
            "keyword": "",
            "bgList": [],
            "workCountryType": 0,
            "workCityList": [],
            "recruitCityList": [],
            "positionFidList": [],
            "pageIndex": page,  # ✅ 使用变量 page
            "pageSize": pagesize,  # ✅ 使用变量 pagesize
        }
        try:
            resp = requests.post(
                f"{url}?timestamp={timestamp}",
                json=payload,
                headers=headers,
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"职位列表抓取失败 page={page}: {e}")
            break

        if not isinstance(data, dict):
            data = {}

        # 调试输出（可选）
        #print(json.dumps(data, indent=4, ensure_ascii=False))

        # ✅ 修改1：正确提取职位列表和总数
        data_obj = data.get("data") or {}
        if not isinstance(data_obj, dict):
            data_obj = {}
        jobs = data_obj.get("positionList", [])
        total = data_obj.get("count", 0)

        for job in jobs:
            post_id = job.get("postId")
            if not post_id:
                print("跳过无效职位：post_id 为空")
                continue
            location = job.get("workCities", "")
            job_url = f"{base_url}?postId={post_id}"
            get_detail(company_id,job_type,post_id,location,job_url)

        if not jobs:
            print("本页无数据，停止")
            break

        all_jobs.extend(jobs)
        print(f"已获取第 {page} 页，本页 {len(jobs)} 条，累计 {len(all_jobs)} / {total} 条")

        # ✅ 修改2：根据总数判断是否完成
        if page * pagesize >= total:
            print("已获取全部职位")
            break

        page += 1
        time.sleep(0.5)

    print(f"最终共获取 {len(all_jobs)} 个职位")

if __name__=="__main__":
    company_id = "C001"
    job_type = 1
    page = int(input("请输入起始页码:"))
    pagesize = int(input("请输入每页条数:"))
    get_joblist(company_id,job_type,page, pagesize)