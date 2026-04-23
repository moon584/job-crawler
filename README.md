# 招聘官网爬虫

本项目用于抓取各公司官方招聘网站的职位信息，并统一存储到 MySQL 数据库中。  
支持分页抓取、自动重试、随机延迟、去重更新以及过期职位软删除，并提供**统一的补爬入口**用于修复缺失的 `description` / `requirement`。

## 特性

- **统一流程**：所有爬虫共用 `global_main.run_crawler`，只需实现三个标准函数即可接入新公司。
- **独立详情函数**：每个爬虫必须导出 `get_detail(post_id, location, job_url, job_type, ...)`，用于主爬和补爬复用。
- **一键补爬**：`python global_rewrite.py` 自动扫描所有公司的空字段职位并分发到对应 `get_detail` 修复。
- **自动分派**：按 `(company_id, job_type)` 精确匹配处理函数，无需手动适配。
- **数据库封装**：`global_db` 提供 `save_to_database`（按 `job_url` 去重插入或更新）和 `search_expired_job`（软删除未抓取到的职位）。
- **健壮请求**：`fetch_with_retry` 支持重试和超时控制。
- **分页与延迟**：自动处理翻页、随机休眠，避免反爬。

## 项目结构

```
招聘官网爬虫/
├── .env                     # 数据库连接配置
├── sql.sql                  # 数据库初始化脚本
├── requirements.txt         # Python 依赖
├── 爬虫名单.pdf
│
└── api爬虫/                 # 核心代码目录
    ├── global_main.py       # 通用函数：请求、延迟、分页流程、标准爬虫入口
    ├── global_db.py         # 数据库操作：入库、过期职位软删除
    ├── global_rewrite.py    # 统一补爬入口：扫描空字段并自动分派到各公司 get_detail
    ├── check_db.py          # 质检报告：统计各公司字段空值率
    ├── db_conn.py           # 数据库连接（从环境变量读取）
    ├── 模板/
    │   └── main_template.py # 新爬虫模板
    ├── 腾讯/
    │   ├── social.py        # 腾讯社招（careers.tencent.com）
    │   └── campus.py        # 腾讯校招/实习（join.qq.com，动态判断类型）
    ├── 美团/
    │   └── main.py          # 美团（校招/社招/实习可选）
    └── 拼多多/
        └── campus.py        # 拼多多（校招/实习）
```

## 使用方法

### 运行主爬虫

```bash
cd api爬虫/腾讯
python social.py      # 腾讯社招
python campus.py      # 腾讯校招/实习

cd ../美团
python main.py

cd ../拼多多
python campus.py
```

### 运行补爬（修复空字段）

```bash
cd api爬虫
python global_rewrite.py
```

自动扫描所有公司 `description`/`requirement` 为空的职位，按 `(company_id, job_type)` 分派到对应 `get_detail` 修复。无需在每个公司目录下单独操作。

### 运行质检报告

```bash
python check_db.py
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
mysql -u root -p < sql.sql   # 在根目录执行
```

### 安装依赖

```bash
pip install -r requirements.txt   # 在根目录执行
```

若没有 `requirements.txt`，手动安装：

```bash
pip install requests pymysql python-dotenv
```

## 添加新爬虫

### 1. 创建目录和文件

```bash
cd api爬虫
mkdir 新公司
# 将 模板/main_template.py 内容复制为 新公司/main.py
```

### 2. 实现核心函数

在 `main.py` 中实现：
- `get_job_type()`：返回招聘类型（0=社招，1=校招，2=实习）
- `fetch_list_page(page, page_size, job_type)`：请求列表页，返回 `(jobs, total_count)`
- `get_detail(post_id, location, job_url, job_type, fallback_job=None)`：获取详情并入库（**必须导出**）
- `process_job(job, job_type)`：调用 `get_detail` 处理单个职位

### 3. 注册到补爬分发表

在 `global_rewrite.py` 的 `_DISPATCH` 字典中添加对应 `(company_id, job_type)` 的条目：

```python
from 新公司.main import get_detail as _new_get_detail

_DISPATCH = {
    # ... 已有条目 ...
    ("C009", 0): _new_get_detail,   # 新公司社招
    ("C009", 1): _new_get_detail,   # 新公司校招
}
```

## 过期职位处理

- 每次全量抓取完成后，会调用 `search_expired_job(company_id, job_type, start_time)`。
- 该函数将 `crawled_at < start_time` 且未被本次抓取更新的职位标记为过期（`is_deleted=1`）。
- 只有爬虫**完整遍历了所有分页**（`current_page * page_size >= total_count`）时才会触发过期软删除，避免因个别网络波动导致误删。

## 质检报告

运行 `api爬虫` 目录下的 `check_db.py`：

```bash
cd api爬虫
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

### Q3：如何补抓缺失的 description/requirements？
直接运行 `python global_rewrite.py` 即可。该脚本自动查询所有公司中这些字段为空的职位，并按公司分发到对应的 `get_detail` 重新抓取更新。

### Q4：不想每次手动输入页码和条数？
可以在调用 `run_crawler` 前直接设置 `start_page=1, page_size=20`，或修改 `get_user_pagination` 逻辑。

### Q5：腾讯 join.qq.com 混合校招和实习怎么办？
该爬虫独立实现了动态类型判断，根据 `projectName` 字段自动区分校招（`job_type=1`）和实习（`job_type=2`），不依赖 `run_crawler`。

## 贡献指南

欢迎添加新公司爬虫。请遵循以下规范：
- 使用 `global_main.run_crawler` 标准流程。
- **必须导出 `get_detail` 函数**，签名与模板一致。
- 在 `global_rewrite.py` 的 `_DISPATCH` 中注册公司分派信息。
- 提交前运行 `check_db.py` 确保关键字段空值率合理。
