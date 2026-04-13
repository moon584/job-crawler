import requests
import time
import json
from db import save_to_database

url = "https://careers.tencent.com/tencentcareer/api/post/Query"
detail_url = "https://careers.tencent.com/tencentcareer/api/post/ByPostId"
base_url = "https://careers.tencent.com/jobdesc.html"


def extract_description_requirement(data):
    """腾讯社招接口：提取职位职责与任职要求。"""
    description = (data.get("Responsibility") or "").strip()
    requirement = (data.get("Requirement") or "").strip()
    return description, requirement


def get_detail(company_id,job_type,post_id,location,job_url):
    timestamp = int(time.time() * 1000)
    try:
        resp = requests.get(
            detail_url,
            params={
                "timestamp": timestamp,
                "postId": post_id,
                "language": "zh-cn"
            },
            timeout=10
        )
        resp.raise_for_status()
        body = resp.json()

        if body.get("Code") != 200:
            print(f"详情接口业务失败 job_url={job_url}, Code={body.get('Code')}")
            return False

        data = body.get("Data") or {}
        if not isinstance(data, dict):
            data = {}

        father = data.get("CategoryName", "")  # 父类（如：技术、产品）
        term = str(data.get("OuterPostTypeID", "")).strip()

        match term:
            # 技术
            case "40001001":
                child = "技术研发"
            case "40001002":
                child = "质量管理"
            case "40001003":
                child = "技术运营"
            case "40001004":
                child = "安全技术"
            case "40001005":
                child = "AI、算法与大数据"
            case "40001006":
                child = "企管"

            # 产品
            case "40002001":
                child = "产品"
            case "40002002":
                child = "游戏产品"
            case "40002003":
                child="项目"
            case "40002004":
                child="金融"

            # 设计
            case "40003001":
                child = "设计"
            case "40003002":
                child = "游戏美术"

            # 营销与公关
            case "40004":
                child = "营销与公关"

            # 销售、服务与支持
            case "40005001":
                child = "销售"
            case "40005002":
                child = "客服"
            # 无子类
            case "40006":
                child = "内容"
            case "40007":
                child = "财务"
            case "40008":
                child = "人力资源"
            case "40009":
                child = "法律与公共策略"
            case "40010":
                child = "行政支持"
            case "40011":
                child = "战略与投资"
            case _:
                child = ""

        category = f"{father}-{child}" if father and child else (father or child)

        title = data.get("RecruitPostName", "")
        description, requirement = extract_description_requirement(data)
        bonus = data.get("ImportantItem", "")
        work_experience=data.get("RequireWorkYearsName", "")
        # 详情接口优先使用返回的标准职位链接
        job_url = data.get("PostURL") or job_url
        publish_time = data.get("LastUpdateTime", "")

        salary = ""
        education = ""


    except Exception as e:
        print(f"爬取失败 job_url={job_url}: {e}")
        return False  # 不保存失败记录

    save_to_database(
        table_name="job",
        columns=["company_id","job_type","title", "category", "description", "requirement", "bonus","location","job_url","work_experience","publish_time"],
        data_tuple=(company_id, job_type,title, category, description, requirement, bonus,location, job_url, work_experience, publish_time),
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
        params = {
            "timestamp": timestamp,
            "countryId": "",
            "cityId": "",
            "bgIds": "",
            "productId": "",
            "categoryId": "",
            "parentCategoryId": "",
            "attrId": 1,
            "keyword": "",
            "pageIndex": page,
            "pageSize": pagesize,
            "language": "zh-cn",
            "area": "cn",
        }
        try:
            resp = requests.get(
                url,
                params=params,
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

        data_obj = data.get("Data") or {}
        if not isinstance(data_obj, dict):
            data_obj = {}
        jobs = data_obj.get("Posts", [])
        total = data_obj.get("Count", 0)

        for job in jobs:
            post_id = job.get("PostId")
            if not post_id:
                print("跳过无效职位：PostId 为空")
                continue
            location = job.get("LocationName", "")
            job_url = job.get("PostURL") or f"{base_url}?postId={post_id}"
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
    job_type = 0
    page = int(input("请输入起始页码:"))
    pagesize = int(input("请输入每页条数:"))
    get_joblist(company_id,job_type,page, pagesize)