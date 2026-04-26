# 招聘官网爬虫

本项目用于抓取各公司官方招聘网站的职位信息，并统一存储到 MySQL 数据库中。  
支持分页抓取、自动重试、随机延迟、去重更新以及过期职位软删除，并提供**统一的补爬脚本**用于修复缺失的 `description` / `requirement`。

## 特性

- **统一流程**：所有爬虫共用 `global_main.run_crawler`，只需实现三个标准函数即可接入新公司。
- **独立详情函数**：每个爬虫必须导出 `get_detail(post_id, location, job_url, job_type, fallback_job=None)`，用于主爬和补爬复用。
- **一键补爬**：`global_rewrite.rewrite_jobs` 自动扫描空字段职位并调用 `get_detail` 修复。
- **数据库封装**：`global_db` 提供 `save_to_database`（按 `job_url` 去重插入或更新）和 `search_expired_job`（软删除未抓取到的职位）。
- **健壮请求**：`fetch_with_retry` 支持重试和超时控制。
- **分页与延迟**：自动处理翻页、随机休眠，避免反爬。

## 快速开始（3 分钟接入新公司）

1. **复制模板文件**  
   将 `main_template.py`（见下文模板）复制为 `新公司_X招/main.py`。

2. **修改配置常量**  
   在 `main.py` 中填写：
   - `COMPANY_ID`（公司唯一标识，与数据库一致）
   - `LIST_API`（职位列表接口 URL）
   - `DETAIL_API`（职位详情接口 URL，若无则留空）
   - `BASE_URL`（职位详情页前缀）
   - 其他请求参数（headers、超时等）

3. **实现四个核心函数**  
   - `get_job_type()`：返回招聘类型（0=社招，1=校招，2=实习），若固定一种可直接 `return 0`。
   - `fetch_list_page(page, page_size, job_type)`：请求列表页，返回 `(jobs, total_count)`。
   - `get_detail(post_id, location, job_url, job_type, fallback_job=None)`：获取详情并入库（**必须导出，供补爬使用**）。
   - `process_job(job, job_type)`：调用 `get_detail` 处理单个职位。

4. **运行主爬虫**  
   ```bash
   cd 新公司_X招
   python C008_1_2.py
   ```

5. **运行补爬（修复空字段）**  
   ```bash
   python rewrite.py   # 每个爬虫目录下需创建 rewrite.py，内容见下文
   ```

6. **验证数据**  
   运行根目录下的 `check_db.py` 生成质检报告。

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
├── tencent_careers/        # 腾讯 careers.tencent.com（社招）
│   ├── main.py
│   └── rewrite.py
├── tencent_join/           # 腾讯 join.qq.com（校招/实习混合）
│   ├── main.py
│   └── rewrite.py
├── meituan/                # 美团（社招/校招/实习可选）
│   ├── main.py
│   └── rewrite.py
├── pdd/                    # 拼多多（校招/实习可选）
│   ├── main.py
│   └── rewrite.py
└── (新公司)/               # 按模板添加的新爬虫
    ├── main.py
    └── rewrite.py
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
# 将下方 main_template.py 内容复制到 C008_1_2.py
```

### 2. 标准模板 `main.py`
见`模板/`文件夹

### 3. 创建 `rewrite.py`（每个爬虫目录必须包含）

```python
from global_rewrite import rewrite_jobs
from main import get_detail

def zhaopin_process(post_id, location, job_url, job_type):
    """适配器：调用官网的 get_detail，返回是否成功"""
    return get_detail(job_type, post_id, location, job_url)

if __name__ == "__main__":
    rewrite_jobs(zhaopin_process)
```

### 4. 调整字段映射

根据实际接口返回的 JSON 结构，修改 `fetch_list_page` 和 `get_detail` 中的字段提取逻辑。  
**务必保证 `save_to_database` 的 `columns` 和 `data_tuple` 顺序一致。**

### 5. 测试运行

```bash
python C008_1_2.py      # 主爬
python rewrite.py   # 补爬
```

## 运行现有爬虫

每个子目录独立运行：

```bash
cd meituan
python C008_1_2.py
```

启动后会提示输入起始页码、每页条数以及招聘类型（若有选项）。  
爬虫将自动分页抓取并入库，最后执行过期职位软删除（当成功抓取数量等于总记录数时）。

## 过期职位处理

- 每次全量抓取完成后，会调用 `search_expired_job(company_id, job_type, start_time)`。
- 该函数将 `crawled_at < start_time` 且未被本次抓取更新的职位标记为过期（`is_deleted=1`）。
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
直接运行 `rewrite.py` 即可。该脚本会自动查询数据库中这些字段为空的职位，并调用 `get_detail` 重新抓取更新。

### Q4：不想每次手动输入页码和条数？
可以在调用 `run_crawler` 前直接设置 `start_page=1, page_size=20`，或修改 `get_user_pagination` 逻辑。

### Q5：join.qq.com 混合校招和实习怎么办？
该爬虫未使用 `run_crawler`，而是独立实现了动态类型判断。如需类似逻辑，可参考 `tencent_join/main.py` 自行实现循环。

## 贡献指南

欢迎添加新公司爬虫。请遵循以下规范：
- 使用 `global_main.run_crawler` 标准流程。
- **必须导出 `get_detail` 函数**，签名与模板一致。
- 每个爬虫目录必须包含 `rewrite.py` 并调用 `rewrite_jobs(get_detail)`。
- 保持 `main.py` 独立，不修改全局文件。
- 提交前运行 `check_db.py` 确保关键字段空值率合理。