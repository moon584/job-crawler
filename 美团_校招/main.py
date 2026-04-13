import requests
import time
import json
from db import save_to_database

url = "https://zhaopin.meituan.com/api/official/job/getJobList"
detail_url = "https://zhaopin.meituan.com/api/official/job/getJobDetail"
base_url = "https://zhaopin.meituan.com/web/position/detail"
headers = {
        "Content-Type": "application/json"
    }

def extract_description_requirement(data):
    """提取职位描述与要求，优先使用常规字段，空值时回退。"""
    description = (data.get("jobDuty") or "").strip()
    requirement = (data.get("jobRequirement") or "").strip()

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
    payload={
        "jobUnionId": post_id,
        "jobShareType": "1"
    }
    try:
        resp = requests.post(
            detail_url,
            json=payload,
            headers=headers,
            timeout=10
        )
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        father = data.get("jobFamily", "")
        child = data.get("jobFamilyGroup", "")
        category = f"{father}-{child}"
        title = data.get("name", "")
        description, requirement = extract_description_requirement(data)
        bonus = data.get("precedence", "")

        salary = ""
        education = ""
        publish_time = ""
        work_experience = data.get("workYear") or ""

    except Exception as e:
        print(f"爬取失败 job_url={job_url}: {e}")
        return False  # 不保存失败记录

    save_to_database(
        table_name="job",
        columns=["company_id","job_type","title", "category", "description", "requirement", "bonus","location","job_url","work_experience"],
        data_tuple=(company_id, job_type,title, category, description, requirement, bonus,location, job_url, work_experience),
        unique_key="job_url"
    )
    return True

def get_joblist(company_id, job_type, page, pagesize, job_type_match, job_type_str):
    all_jobs = []
    while True:
        payload = {
                "page": {
                    "pageNo": page,
                    "pageSize": pagesize
                },
                "jobShareType": "1",
                "keywords": "",
                "cityList": [],
                "department": [],
                "jfJgList": [],
                "jobType": job_type_match,
                "typeCode": [],
                "specialCode": [],
                "u_query_id": "",
                "r_query_id": ""
            }
        try:
            resp = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"职位列表抓取失败 page={page}: {e}")
            crawl_ok = False
            break

        if not isinstance(data, dict):
            data = {}

        # 调试输出（可选）
        #print(json.dumps(data, indent=4, ensure_ascii=False))

        # ✅ 修改1：正确提取职位列表和总数
        data_obj = data.get("data") or {}
        if not isinstance(data_obj, dict):
            data_obj = {}
        jobs = data_obj.get("list", [])
        if not isinstance(jobs, list):
            jobs = []

        page_info = data_obj.get("page")
        if not isinstance(page_info, dict):
            page_info = {}
        total = page_info.get("totalCount", 0)

        if not isinstance(total, int):
            try:
                total = int(total)
            except (TypeError, ValueError):
                total = 0

        for job in jobs:
            post_id = job.get("jobUnionId")
            if not post_id:
                print("跳过无效职位：post_id 为空")
                continue

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

            job_url = f"{base_url}?jobUnionId={post_id}&highlightType={job_type_str}"
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
    company_id = "C007"
    job_type = int(input("请输入招聘类型(0=社招，1=校招): "))
    page = int(input("请输入起始页码:"))
    pagesize = int(input("请输入每页条数:"))
    if job_type == "1":
        job_type_match=[
                    {"code": "1", "subCode": []},
                    {"code": "2", "subCode": []}
        ]
        job_type_str= "campus"
    else:
        job_type_match=[{"code": "3", "subCode": []}]
        job_type_str= "social"
    get_joblist(company_id,job_type,page, pagesize,job_type_match,job_type_str)