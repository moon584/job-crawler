
# 招聘官网爬虫

本项目用于抓取招聘官网职位信息并写入 MySQL，当前目录里有多个来源实现。

为了快速接入新官网，推荐直接复制一个现有目录作为模板。本文以 `腾讯_校招` 为例，说明最短配置流程。

## 0. 3 分钟快速开始

按下面顺序执行即可跑通一条新来源链路：

1. 复制模板目录 `腾讯_校招` 为 `新公司_校招`
2. 修改 `新公司_校招/main.py`、`新公司_校招/rewrite.py`（只改业务抓取/解析逻辑）
3. 运行主爬虫 -> 运行补爬 -> 运行质检报告

```powershell
cd A:\招聘官网爬虫
Copy-Item .\腾讯_校招 .\新公司_校招 -Recurse
cd .\新公司_校招
python .\main.py
python .\rewrite.py
cd ..
python .\check_db.py
```

说明：`sql.sql` 与依赖安装请按后续第 3 节执行一次即可。

## 1. 先复制模板目录

在项目根目录执行：

```powershell
cd A:\招聘官网爬虫
Copy-Item .\腾讯_校招 .\新公司_校招 -Recurse
```

把 `新公司_校招` 改成你的目标来源名称（例如 `字节_校招`）。

## 2. 配置流程（只改这几个文件）

> 注意：项目已将数据库连接逻辑集中到根目录下的 `db_conn.py`，各子目录下的 `db.py` 与 `rewrite.py` 已改为在运行时调用 `db_conn.connect_db()`。
>
> 因此你通常不需要修改 `db.py` 的硬编码配置，只需通过环境变量或 `.env` 文件配置数据库连接信息（见下文）。

### 2.1 改 `新公司_校招/main.py`

按新官网接口修改以下内容：

- `url`：职位列表接口
- `detail_url`：职位详情接口
- `base_url`：官网职位详情页前缀
- `get_joblist(...)`：列表字段映射（职位列表、总数、职位唯一 ID）
- `get_detail(...)`：详情字段映射（`title`、`category`、`description`、`requirement`、`location`、`job_url` 等）
- `__main__`：`company_id`、`job_type`（社招=0，校招=1）

要求：`save_to_database(...)` 的 `columns` 和 `data_tuple` 顺序必须一一对应。

### 2.2 数据库配置（改为环境变量）

项目使用 `db_conn.py` 统一读取环境变量来建立数据库连接。请通过系统环境或项目根 `.env` 文件提供以下环境变量：

示例 `.env`（放在项目根）：

```
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password_here
DB_NAME=job_recruitment
DB_CHARSET=utf8mb4
```

如何验证连接：在项目根运行 `test_conn.py`：

```powershell
pip install python-dotenv pymysql
python .\test_conn.py
```

你应看到控制台输出 `数据库连接成功` 或 `数据库连接失败: <错误信息>`。

当前入库策略仍按 `job_url` 去重：

- 存在则更新
- 不存在则插入

### 2.3 改 `新公司_校招/rewrite.py`

用于补爬空字段：

- `_extract_post_id(job_url)`：按新官网链接规则提取岗位 ID
- `_retry_single_job(...)`：请求新官网详情并回写 `description`、`requirement`

子模块不再在导入时强制读取环境变量或抛错，连接在运行时建立，若连接失败会有明确的日志提示。

## 3. 运行顺序

### 3.1 初始化数据库

先执行根目录 `sql.sql`：

```powershell
cd A:\招聘官网爬虫
mysql -u root -p < .\sql.sql
```

### 3.2 安装依赖

建议在虚拟环境中安装依赖：

```powershell
cd A:\招聘官网爬虫
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
# 如果没有 requirements.txt，可单独安装：
pip install requests pymysql python-dotenv
```

### 3.3 跑主爬虫

```powershell
cd A:\招聘官网爬虫\新公司_校招
python .\main.py
```

### 3.4 跑补爬

```powershell
cd A:\招聘官网爬虫\新公司_校招
python .\rewrite.py
```

### 3.5 跑质检报告

```powershell
cd A:\招聘官网爬虫
python .\check_db.py
```

输出文件：`check_db_report.md`。

## 4. 项目逻辑说明（对应核心脚本）

- `main.py`：分页抓列表 -> 拉详情 -> 字段提取 -> 调用 `db.py` 入库
- `db.py`：调用 `db_conn.connect_db()` 建立连接并统一写库逻辑（按唯一键去重更新）
- `rewrite.py`：修复 `description` / `requirement` 为空的数据
- `check_db.py`：统计空值与分类数量，输出检查报告

## 5. 新来源接入完成标准

满足以下四点即可认为接入完成：

1. 能全量翻页抓取职位列表
2. 每个职位有稳定唯一键（建议 `job_url`）
3. 详情可提取 `description` 和 `requirement`
4. `check_db.py` 报告中，新来源有数据且关键字段空值可接受

