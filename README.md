# 招聘官网爬虫

本项目用于抓取各公司官方招聘网站的职位信息，并统一存储到 MySQL 数据库中。支持分页抓取、自动重试、随机延迟、去重更新以及过期职位软删除。

## 特性

- **统一流程**：所有爬虫共用 `global_main.run_crawler`，只需实现三个标准函数即可接入新公司。
- **数据库封装**：`global_db` 提供 `save_to_database`（按 `job_url` 去重插入或更新）和 `search_expired_job`（软删除本次未抓取到的职位）。
- **健壮请求**：`fetch_with_retry` 支持重试和超时控制。
- **分页与延迟**：自动处理翻页、随机休眠，避免反爬。

## 快速开始（3 分钟接入新公司）

1. **复制模板文件**  
   将 `main_template.py`复制为 `新公司_X招/main.py`。

2. **修改配置常量**  
   在 `main.py` 中填写：
   - `COMPANY_ID`（公司唯一标识，与数据库一致）
   - `LIST_API`（职位列表接口 URL）
   - `DETAIL_API`（职位详情接口 URL，若无则留空）
   - `BASE_URL`（职位详情页前缀）
   - 其他请求参数（headers、超时等）

3. **实现三个标准函数**  
   - `get_job_type()`：返回招聘类型（0=社招，1=校招，2=实习），若固定一种可直接 `return 0`。
   - `fetch_list_page(page, page_size, job_type)`：请求列表页，返回 `(jobs, total_count)`。
   - `process_job(job, job_type)`：处理单个职位（请求详情、字段映射、入库），返回是否成功。

4. **运行爬虫**  
   ```bash
   cd 新公司_X招
   python main.py
   ```

5. **验证数据**  
   运行根目录下的 `check_db.py` 生成质检报告，确认关键字段不为空。

## 项目结构

```
招聘官网爬虫/
├── global_main.py          # 通用函数：请求、延迟、分页流程、标准爬虫入口
├── global_db.py            # 数据库操作：入库、过期职位软删除
├── check_db.py             # 质检报告：统计各公司字段空值率
├── sql.sql                 # 数据库初始化脚本
├── requirements.txt        # Python 依赖
├── tencent_careers/        # 腾讯 careers.tencent.com（社招）
│   └── main.py
├── tencent_join/           # 腾讯 join.qq.com（校招/实习混合）
│   └── main.py
├── meituan/                # 美团（社招/校招/实习可选）
│   └── main.py
├── pdd/                    # 拼多多（校招/实习可选）
│   └── main.py
└── (新公司)/               # 按模板添加的新爬虫
    └── main.py
```

## 数据库配置

项目通过环境变量或 `.env` 文件读取数据库连接信息。

```ini
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=job_recruitment
DB_CHARSET=utf8mb4
```

### 初始化数据库

执行根目录下的 `sql.sql` 创建表：

```bash
mysql -u root -p < sql.sql
```

### 安装依赖

```bash
pip install -r requirements.txt
```

若没有 `requirements.txt`，手动安装：

```bash
pip install requests pymysql python-dotenv
```

## 添加新爬虫（详细步骤）

### 1. 创建目录并复制模板

```bash
mkdir 新公司_校招
cd 新公司_校招
# 复制下方模板内容到 main.py
```

### 2. 标准模板 `main_template.py`

```python
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

# ---------- 标准接口函数（必须实现）----------
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

    resp = fetch_with_retry("POST", LIST_API, json=payload, timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
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
    处理单个职位：获取详情（可选）并保存到数据库。
    :param job:        列表中的职位字典（至少包含唯一标识字段，如 post_id）
    :param job_type:   招聘类型
    :return:           是否成功保存（True/False）
    """
    # 1. 从列表数据中提取必要字段
    post_id = job.get("postId") or job.get("id")
    if not post_id:
        print("跳过无效职位：缺少唯一标识")
        return False

    location = job.get("city", "") or job.get("location", "")
    job_url = f"{BASE_URL}?id={post_id}"

    # 2. （可选）请求详情接口获取更多字段
    detail_data = {}
    if DETAIL_API:
        params = {"id": post_id}
        resp = fetch_with_retry("GET", DETAIL_API, params=params, timeout=REQUEST_TIMEOUT, retry_times=RETRY_TIMES)
        if resp:
            detail_data = resp.get("data") or {}

    # 3. 提取最终字段（优先使用详情数据，降级使用列表数据）
    title = detail_data.get("title") or job.get("title") or "无标题"
    category = detail_data.get("category") or job.get("category") or "未分类"
    description, requirement = extract_description_requirement(detail_data)
    bonus = detail_data.get("bonus") or job.get("bonus", "")
    work_experience = detail_data.get("workYear") or job.get("workYear", "")
    salary = detail_data.get("salary") or None
    education = detail_data.get("education") or None
    publish_time = detail_data.get("publishTime") or None

    # 4. 入库
    try:
        save_to_database(
            status=0,
            table_name="job",
            columns=["company_id", "job_type", "job_url", "post_id", "title",
                     "category", "description", "requirement", "bonus",
                     "location", "salary", "education", "publish_time", "work_experience"],
            data_tuple=(COMPANY_ID, job_type, job_url, str(post_id), title,
                        category, description, requirement, bonus,
                        location, salary, education, publish_time, work_experience),
            unique_key="job_url"
        )
        return True
    except Exception as e:
        print(f"写库失败 {job_url}: {e}")
        return False

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
```

### 3. 调整字段映射

根据实际接口返回的 JSON 结构，修改 `fetch_list_page` 和 `process_job` 中的字段提取逻辑。
务必保证 `save_to_database` 的 `columns` 和 `data_tuple` 顺序一致。

### 4. 测试运行

```bash
python main.py
```

## 运行现有爬虫

每个子目录独立运行：

```bash
cd meituan
python main.py
```

启动后会提示输入起始页码、每页条数以及招聘类型（若有选项）。
爬虫将自动分页抓取并入库，最后执行过期职位软删除（当成功抓取数量等于总记录数时）。

## 过期职位处理

- 每次全量抓取完成后，会调用 `search_expired_job(company_id, job_type, start_time)`。
- 该函数将 `publish_time < start_time` 且未被本次抓取更新的职位状态标记为过期（`status=1`）。
- 因此确保每次抓取**完整全量数据**才能正确标记过期。

## 质检报告

运行根目录下的 `check_db.py`：

```bash
cd 招聘官网爬虫
python check_db.py
```

将生成 `check_db_report.md`，包含各公司各类型职位的总数、关键字段空值统计等，用于验证爬虫质量。

## 常见问题

### Q1：入库时提示字段不匹配？
检查 `columns` 和 `data_tuple` 的顺序是否完全一致，数量是否相同。

### Q2：请求返回 None？
- 检查网络连接和接口 URL 是否正确。
- 尝试增加 `RETRY_TIMES` 或 `timeout`。
- 部分接口需要添加 `headers`（如 `User-Agent`），可在 `fetch_with_retry` 中通过 `headers` 参数传入。

### Q3：如何补抓缺失的 description/requirement？
由于 `save_to_database` 使用 `job_url` 作为唯一键，**重新运行爬虫**时会更新已存在的记录。
因此若某字段首次抓取为空，修复解析逻辑后再次运行即可覆盖。

### Q4：不想每次手动输入页码和条数？
可以在调用 `run_crawler` 前直接设置 `start_page=1, page_size=20`，或修改 `get_user_pagination` 逻辑。

### Q5：join.qq.com 混合校招和实习怎么办？
该爬虫未使用 `run_crawler`，而是独立实现了动态类型判断。
如需类似逻辑，可参考 `tencent_join/main.py` 自行实现循环。

## 贡献指南

欢迎添加新公司爬虫。请遵循以下规范：
- 使用 `global_main.run_crawler` 标准流程。
- 保持 `main.py` 独立，不修改全局文件。
- 提交前运行 `check_db.py` 确保关键字段空值率合理。