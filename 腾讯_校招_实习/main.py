import requests
import time
from db import save_to_database, search_expired_job
from datetime import datetime

url = "https://join.qq.com/api/v1/position/searchPosition"
detail_url = "https://join.qq.com/api/v1/jobDetails/getJobDetailsByPostId"
base_url = "https://join.qq.com/post_detail.html"

all_jobs = []
total=0
# ----------------------------------------------------------------------------
# 说明：此文件包含从腾讯招聘接口抓取列表与详情的主逻辑。
# - `get_joblist` 负责分页抓取职位列表，并调用 `get_detail` 写入数据库。
# - `get_detail` 负责根据 postId 请求详情并提取 description/requirement，然后调用 db.save_to_database
# - `extract_description_requirement` 是一个工具函数，用于从返回的 JSON 中提取职位描述与要求
# ----------------------------------------------------------------------------

def extract_description_requirement(data):
    """
    提取职位描述与要求（中文注释）：
    - 优先从常规字段 `desc` / `request` 读取。
    - 若为空则回退到 `topicDetail` / `topicRequirement`。
    - 若仍为空，尝试从 `subDirectionDtos` 列表中的第一个元素的 `subDirection` 字段中提取。

    返回值：tuple(description, requirement)
    """
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
    # 根据 post_id 请求岗位详情并解析需要写入数据库的字段
    # company_id, job_type 是业务相关字段，用于写库时标识来源与类型
    global all_jobs, total
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
        # 请求或解析异常时仅打印日志，不将失败记录写入数据库
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
    # 分页抓取职位列表，参数：
    # - company_id, job_type: 业务标识
    # - page, pagesize: 分页参数
    global all_jobs, total
    headers = {
        "Content-Type": "application/json"
    }
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

        # 遍历当前页的职位列表并逐条抓详情写库
        for job in jobs:
            post_id = job.get("postId")
            if not post_id:
                # 若没有 postId 则无法定位详情，跳过
                print("跳过无效职位：post_id 为空")
                continue
            location = job.get("workCities", "")
            job_url = f"{base_url}?postId={post_id}"

            # 若职位类型字符串中包含“实习”，则视为实习类（2）
            job_type_str = job.get("projectName")
            if isinstance(job_type_str, str) and "实习" in job_type_str:
                job_type = 2

            get_detail(company_id,job_type,post_id,location,job_url)

        if not jobs:
            # 如果本页没有数据，认为已到末尾，停止抓取
            print("本页无数据，停止")
            break

        all_jobs.extend(jobs)
        # 打印当前进度信息
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

    start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    get_joblist(company_id,job_type,page, pagesize)

    if len(all_jobs) == total:
        search_expired_job(company_id, job_type, start_time)
