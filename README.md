# 招聘官网爬虫

本项目用于抓取各公司官方招聘网站的职位信息，并统一存储到 MySQL 数据库中。  
支持分页抓取、自动重试、随机延迟、去重更新以及过期职位软删除，并提供**统一的补爬脚本**用于修复缺失的 `description` / `requirement`。

## 特性

- **统一流程**：所有爬虫共享 `global_main` 中的 `run_crawler` / `crawl_job_list_generic`，只需实现三个标准函数即可接入。
- **独立详情函数**：每个爬虫导出 `get_detail(post_id, location, job_url, job_type, fallback_job=None)`，供主爬和补爬复用。
- **一键补爬**：`global_rewrite.rewrite_jobs` 自动扫描空字段职位并调用 `get_detail` 修复。
- **数据库封装**：`global_db` 提供 `save_to_database`（按 `job_url` 去重插入或更新）和 `search_expired_job`（软删除未抓取到的职位）。
- **健壮请求**：`fetch_with_retry` 支持重试和超时控制。
- **分页与延迟**：自动处理翻页、随机休眠，避免反爬。

## 项目结构

```
招聘官网爬虫/
├── global_main.py          # 通用函数：请求、延迟、分页流程、标准爬虫入口
├── global_db.py            # 数据库操作：入库、过期职位软删除
├── global_rewrite.py       # 通用补爬脚本：扫描空字段并调用 get_detail 修复
├── check_db.py             # 质检报告：统计各公司字段空值率
├── sql.sql                 # 数据库初始化脚本
├── requirements.txt        # Python 依赖
├── db_conn.py              # 数据库连接（从环境变量读取）
│
├── 腾讯/                   # 腾讯（C001）
│   ├── __init__.py
│   ├── social.py           # 社招（careers.tencent.com）
│   └── campus.py           # 校招/实习（join.qq.com，动态检测 job_type）
│
├── 阿里巴巴/
│   ├── __init__.py
│   └── campus.py           # 校招/实习（campus-talent.alibaba.com，多批次）
│
├── 美团/
│   ├── __init__.py
│   └── main.py             # 社招/校招/实习可选（zhaopin.meituan.com）
│
├── 拼多多/
│   ├── __init__.py
│   └── campus.py           # 校招/实习（careers.pinduoduo.com）
│
├── 网易/                   # 网易（C005）
│   ├── __init__.py          # ⭐ 统一入口：三站依次爬完再统一过期检查
│   ├── intern_1.py          # 主站实习（hr.163.com）
│   ├── intern_2.py          # 互娱实习（campus.game.163.com）
│   └── intern_3.py          # 雷火实习（xiaozhao.leihuo.netease.com）
│
└── (新公司)/               # 按模板添加的新爬虫
    ├── __init__.py
    └── main.py
```

## 数据库配置

项目通过环境变量或 `.env` 文件读取数据库连接信息。在项目根目录创建 `.env` 文件：

```ini
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=job_recruitment
DB_CHARSET=utf8mb4
```

### 初始化数据库

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

## 运行爬虫

### 单公司统一运行（推荐）

```bash
python -m 网易      # 依次爬取网易三个子站，全部完成后统一过期检查
python -m 腾讯      # 爬取腾讯社招+校招
python -m 美团      # 爬取美团
python -m 拼多多    # 爬取拼多多
```

### 单独运行某个子爬虫（调试用）

```bash
python 网易/intern_1.py
python 腾讯/social.py
```

启动后会提示输入起始页码、每页条数以及招聘类型（若有选项）。

## 过期职位处理

- 每次全量抓取完成后，调用 `search_expired_job(company_id, job_type, start_time)`。
- 将 `crawled_at < start_time` 且未被本次抓取更新的职位标记为过期（`is_deleted=1`）。
- **注意**：如果同一公司有多个爬虫共享 `company_id` + `job_type`（如网易 C005+实习），必须等所有子站爬完再统一过期检查，否则先跑的会被后跑的误删。网易的做法是用 `__init__.py` 统一编排。

## 补爬（修复空缺字段）

统一补爬脚本 `global_rewrite.py` 自动分发到各公司：

```bash
python global_rewrite.py
```

它会扫描数据库中 `description` 或 `requirement` 为空的记录，按 `(company_id, job_type)` 自动查找对应爬虫的 `get_detail` 函数进行修复。

### 注册新公司到补爬

在 `global_rewrite.py` 的 `_DISPATCH` 字典中添加：

```python
from 新公司.main import get_detail as _new_get_detail

_DISPATCH = {
    ...
    ("C00X", 0): _new_get_detail,  # 社招
    ("C00X", 2): _new_get_detail,  # 实习
}
```

只有真正有详情接口的爬虫才需要注册。如果列表接口已含全部信息（无详情接口），注册到补爬没有意义。

## 添加新爬虫

### 1. 创建文件

在公司文件夹下创建 Python 文件，参考现有实现或 `AAA模板/main_template.py`。

### 2. 实现标准接口

每个爬虫需要实现：

| 函数 | 用途 | 说明 |
|------|------|------|
| `get_detail(post_id, location, job_url, job_type, fallback_job=None)` | 获取详情并入库 | 必须导出，供主爬和补爬复用 |
| `get_job_type()` | 返回招聘类型 | 若固定一种类型可直接 `return 0` |
| `fetch_list_page(page, page_size, job_type)` | 请求列表页 | 返回 `(jobs, total_count)` |
| `process_job(job, job_type)` | 处理单个职位 | 通常调 `get_detail` |

### 3. 出口函数

```python
def run_crawl(start_page: int, page_size: int, max_items: int):
    """供统一入口调用的爬取函数，不做出检查"""
    return crawl_job_list_generic(job_type=..., start_page=start_page,
        page_size=page_size, fetch_list_page_func=fetch_list_page,
        process_job_func=process_job, base_delay=1.0, max_items=max_items)
```

### 4. 创建公司统一入口

在公司 `__init__.py` 中编排所有子爬虫：

```python
from global_main import get_user_pagination, get_max_items, search_expired_job
from .sub_crawler import run_crawl as crawl_a
from .sub_crawler2 import run_crawl as crawl_b

def main():
    start_page, page_size = get_user_pagination()
    max_items = get_max_items()
    start_time = ...

    # 依次运行所有子爬虫
    for name, func in [("A站", crawl_a), ("B站", crawl_b)]:
        saved, fetched, completed = func(start_page, page_size, max_items)
        ...

    # 全部完成后统一过期检查
    if all_completed:
        search_expired_job(COMPANY_ID, job_type, start_time)
```

### 5. 注册到补爬

在 `global_rewrite.py` 中添加分发表条目。

## 常见问题

### Q1：入库时提示字段不匹配？
检查 `columns` 和 `data_tuple` 的顺序是否完全一致，数量是否相同。

### Q2：请求返回 None？
- 检查网络连接和接口 URL 是否正确。
- 尝试增加 `RETRY_TIMES` 或 `timeout`。
- 部分接口需要添加 `headers`（如 `User-Agent`），可在 `fetch_with_retry` 中通过 `headers` 参数传入。

### Q3：如何补抓缺失的 description/requirement？
直接运行 `python global_rewrite.py` 即可。该脚本自动查询数据库中这些字段为空的职位，按 `(company_id, job_type)` 分发给对应爬虫的 `get_detail`。

### Q4：同一公司多个爬虫共享 company_id，过期检查误删怎么办？
不要让每个子爬虫单独做过期检查。改为统一入口编排：所有子站爬完后再统一调用一次 `search_expired_job`。详见网易 `__init__.py` 的做法。

### Q5：API 返回的页大小和请求的不一致？
某些接口忽略客户端传入的 `pageSize` 参数，使用固定页大小（如 15 条/页）。如果分页判断 `current_page * page_size >= total_count` 提前触发，可在请求中加上 `pageSize` 参数匹配用户输入，或改用 `crawl_job_list_generic` 自行控制分页。

## 质检报告

运行根目录下的 `check_db.py`：

```bash
python check_db.py
```

将生成 `check_db_report.md`，包含各公司各类型职位的总数、关键字段空值统计等，用于验证爬虫质量。
