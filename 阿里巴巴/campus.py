"""
阿里巴巴招聘爬虫（campus-talent.alibaba.com）
固定抓取实习职位（job_type=2），支持多批次选择
"""

import re
import requests
from datetime import datetime
from global_main import fetch_with_retry, get_user_pagination, get_max_items, \
    crawl_job_list_generic, search_expired_job
from global_db import save_to_database

# ---------- 配置 ----------
COMPANY_ID = "C002"
MAIN_URL = "https://campus-talent.alibaba.com/"
LIST_API = "https://campus-talent.alibaba.com/position/search"
DETAIL_API = "https://campus-talent.alibaba.com/position/detail"
BASE_URL = "https://campus-talent.alibaba.com/campus/position"
REQUEST_TIMEOUT = 10
RETRY_TIMES = 2

# 所有实习批次
BATCHES = [
    {"id": 100000540002, "name": "阿里巴巴2027届实习生"},
    {"id": 100000560002, "name": "阿里巴巴日常实习生"},
    {"id": 100000560001, "name": "阿里巴巴研究型实习生"},
]

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})
_csrf_token = None
_current_batch_id = BATCHES[0]["id"]


def _ensure_csrf():
    """访问主页获取 _csrf token 和 cookies"""
    global _csrf_token
    if _csrf_token is not None:
        return _csrf_token, _session.cookies.get_dict()

    try:
        resp = _session.get(MAIN_URL, timeout=REQUEST_TIMEOUT)
        # 尝试从 cookie 中获取（常见名称：XSRF-TOKEN, _csrf, csrf_token）
        for cookie in _session.cookies:
            name = cookie.name.lower()
            if any(k in name for k in ("csrf", "xsrf")):
                _csrf_token = cookie.value
                print(f"从 cookie '{cookie.name}' 获取到 CSRF token")
                return _csrf_token, _session.cookies.get_dict()

        # 从页面 HTML 中提取（多种模式）
        patterns = [
            r'_csrf["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'csrf-token["\']?\s*content=["\']([^"\']+)["\']',
            r'csrfToken["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'window\._csrf\s*=\s*["\']([^"\']+)["\']',
        ]
        for pat in patterns:
            m = re.search(pat, resp.text)
            if m:
                _csrf_token = m.group(1)
                print("从页面 HTML 获取到 CSRF token")
                return _csrf_token, _session.cookies.get_dict()

        # 仍然没找到，打印前 2000 字符帮忙排查
        print("未找到 CSRF token，页面内容前 2000 字符：")
        print(resp.text[:2000])
        _csrf_token = ""
        return _csrf_token, _session.cookies.get_dict()
    except Exception as e:
        print(f"获取 CSRF token 失败: {e}")
        _csrf_token = ""
        return _csrf_token, {}


# ---------- 辅助函数 ----------
def extract_description_requirement(data: dict):
    description = (data.get("description") or "").strip()
    requirement = (data.get("requirement") or "").strip()
    return description, requirement


def get_detail(post_id: str, location: str, job_url: str, job_type: int, fallback_job: dict = None) -> bool:
    """获取详情并入库"""
    csrf, cookies = _ensure_csrf()
    payload = {"id": post_id, "channel": "campus_group_official_site", "language": "zh"}
    resp_json = fetch_with_retry("POST", f"{DETAIL_API}?_csrf={csrf}", json=payload,
                                 cookies=cookies, timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
    data = resp_json.get("content") if resp_json else {}
    if not isinstance(data, dict):
        data = {}

    title = (data.get("name") or "").strip()
    category = (data.get("categoryName") or "").strip()
    description, requirement = extract_description_requirement(data)

    if fallback_job and isinstance(fallback_job, dict):
        if not title:
            title = (fallback_job.get("name") or "").strip()
        if not category:
            category = (fallback_job.get("categoryName") or "").strip()
        if not description:
            description = (fallback_job.get("description") or "").strip()
        if not requirement:
            requirement = (fallback_job.get("requirement") or "").strip()
        if not location:
            locs = fallback_job.get("workLocations") or []
            location = "、".join(locs) if isinstance(locs, list) else str(locs)

    if not title:
        title = f"职位_{post_id}"
    if not category:
        category = "未分类"

    try:
        save_to_database(
            status=0,
            table_name="job",
            columns=["company_id", "job_type", "job_url", "post_id", "title",
                     "category", "description", "requirement", "bonus",
                     "location", "salary", "education", "publish_time", "work_experience"],
            data_tuple=(COMPANY_ID, job_type, job_url, str(post_id), title,
                        category, description, requirement, "",
                        location, "", "", "", ""),
            unique_key="job_url"
        )
        return True
    except Exception as e:
        print(f"写库失败 {job_url}: {e}")
        return False


# ---------- 标准接口函数（供 crawl_job_list_generic 使用）----------
def get_job_type() -> int:
    return 2


def fetch_list_page(page: int, page_size: int, job_type: int):
    csrf, cookies = _ensure_csrf()
    payload = {
        "batchId": _current_batch_id,
        "pageIndex": page,
        "pageSize": page_size,
        "channel": "campus_group_official_site",
        "language": "zh",
    }
    resp = fetch_with_retry("POST", f"{LIST_API}?_csrf={csrf}", json=payload,
                            cookies=cookies, timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
    if not resp:
        return [], 0
    content = resp.get("content") or {}
    jobs = content.get("datas", [])
    total = content.get("totalCount", 0)
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = 0
    return jobs, total


def process_job(job: dict, job_type: int) -> bool:
    post_id = job.get("id")
    if not post_id:
        return False

    job_url = f"{BASE_URL}/{post_id}?deptCodes="
    locs = job.get("workLocations") or []
    location = "、".join(locs) if isinstance(locs, list) else str(locs)

    return get_detail(str(post_id), location, job_url, job_type, fallback_job=job)


# ---------- 批次选择 ----------
def select_batches() -> list:
    """用户选择要爬取的批次"""
    print("\n可选实习批次：")
    for i, b in enumerate(BATCHES, 1):
        print(f"  {i}. {b['name']}")
    print(f"  {len(BATCHES) + 1}. 全部爬取")
    while True:
        try:
            choice = int(input(f"请选择（1-{len(BATCHES) + 1}，默认1）: ") or "1")
            if 1 <= choice <= len(BATCHES):
                return [BATCHES[choice - 1]]
            elif choice == len(BATCHES) + 1:
                return BATCHES
            print(f"请输入 1-{len(BATCHES) + 1}")
        except ValueError:
            print(f"输入无效，请输入数字 1-{len(BATCHES) + 1}")


# ---------- 入口 ----------
def main():
    global _current_batch_id

    batches = select_batches()
    if not batches:
        return

    start_page, page_size = get_user_pagination()
    max_items = get_max_items()
    start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    total_saved = 0
    total_fetched = 0
    all_completed = True
    crawl_all_batches = len(batches) == len(BATCHES)

    for batch in batches:
        _current_batch_id = batch["id"]
        print(f"\n=== 爬取批次: {batch['name']} ===")

        saved, fetched, completed = crawl_job_list_generic(
            2, start_page, page_size,
            fetch_list_page, process_job,
            base_delay=1.0, max_items=max_items
        )
        total_saved += saved
        total_fetched += fetched
        if not completed:
            all_completed = False
        print(f"  该批次完成: 保存 {saved} / 获取 {fetched}")

    print(f"\n所有批次完成，共保存 {total_saved} 个职位，共获取 {total_fetched} 个")
    if crawl_all_batches and all_completed and total_fetched > 0:
        search_expired_job(COMPANY_ID, 2, start_time)
    else:
        print("未完整爬取全量数据，跳过过期检查")


if __name__ == "__main__":
    main()
