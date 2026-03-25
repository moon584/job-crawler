# 腾讯招聘爬虫

用于按公司分类抓取腾讯招聘官网岗位信息，支持配置化扩展与增量写库。

## 目录
- [环境要求](#环境要求)
- [安装与配置](#安装与配置)
- [运行方式](#运行方式)
- [规则文件说明](#规则文件说明)
- [常见问题](#常见问题)
- [测试](#测试)
- [数据维护](#数据维护)

## 环境要求
- Python 3.11+（当前开发环境为 3.13）
- MySQL 5.7+/8.0，用于存储 `company/category/job` 数据
- 可访问腾讯招聘接口的网络环境

## 安装与配置
1. **克隆项目并安装依赖**

```bash
pip install -r requirements.txt
```

2. **复制环境变量模板**

```bash
copy .env.example .env  # Windows
# 或
cp .env.example .env    # macOS/Linux
```

根据自身环境填写 `.env`，字段说明如下：

| 变量名        | 说明                       | 默认值 |
|---------------|----------------------------|--------|
| `DB_HOST`     | MySQL 地址                 | 127.0.0.1 |
| `DB_PORT`     | MySQL 端口                 | 3306 |
| `DB_USER`     | 数据库用户名               | root |
| `DB_PASSWORD` | 数据库密码                 | （空） |
| `DB_NAME`     | 数据库名称                 | job_system |

> 任何敏感信息都放在 `.env`，文件已在 `.gitignore` 中忽略，避免泄漏。

3. **准备规则文件**
   - `rules/company.json` 存放各公司的 API 规则。
   - `extra.default_category_id`（数据库 ID）与 `extra.default_api_category_id`（接口分类 ID，可为任意字符串）需要成对配置，便于兜底。

4. **数据库准备**
   - 执行 `sql.sql` 初始化数据结构。
   - 确保 `categoryid` 值与官网接口一致，必要时可用 `crawler.utils.normalize_category_id` 清洗并统一大小写。
   - `category` 表中的 `crawled_job_count`（实际写入 job 表的数量）与 `official_job_count`（上一次爬虫抓取到的总条数）由程序在每次抓取后自动回写，首次可全部置 0 作为基线。

## 运行方式

```bash
python main.py --rules rules/company.json [--env-file .env] [--dry-run]
```

运行时交互步骤：
1. 输入公司 ID（如 `C001`）。
2. 选择招聘类型：`0` 社会招聘，`1` 校园招聘。
3. 输入要抓取的分类 ID，逗号分隔或输入 `all` 全部分类。
4. 输入每个分类抓取条数，数字或 `all`。
5. 程序会在开抓前比较 `category.official_job_count` 与 `crawled_job_count`，若相等直接跳过该分类并给出提示；否则继续抓取。本轮抓取结束后会把 `official_job_count` 设置为“本次真实抓到的条数”，`crawled_job_count` 设置为数据库当前写入的条数。如发现数据库旧数据多于本轮抓到的条数，将先清空该分类的职位再重新写入，避免冗余数据。

常用参数：
- `--env-file`: 指定自定义 env 文件。
- `--dry-run`: 仅打印写库数据，不改动数据库。
- `--provider`: 手动指定 provider 名称（默认为规则中的 `provider`）。

### 启动前检查
1. 数据库连通、表结构一致。
2. `.env`/环境变量已配置。
3. `rules/company.json` 中对应 `company_id` 的配置存在并最新。
4. 如需默认分类兜底，`default_category_id` 与 `default_api_category_id` 均已填写。

## 规则文件说明

```json
{
  "company_id": "C001",
  "provider": "config",
  "list_api": { "url": "https://...", "default_params": { ... } },
  "detail_api": { "url": "https://...", "default_params": { ... } },
  "throttle": { "min_seconds": 0.5, "max_seconds": 1.0, "max_retries": 3, "retry_backoff": 2.0, "timeout": 15 },
  "extra": {
    "list": { "posts_path": "Data.Posts", ... },
    "detail": { "data_path": "Data", ... },
    "field_map": { "title": "RecruitPostName", ... },
    "default_values": { "salary": "面议" },
    "default_category_id": "CATDEFAULT",
    "default_api_category_id": "40001001"
  }
}
```

- `list_api/detail_api`: 接口地址和基础参数。
- `throttle`: 每次请求的最小/最大延迟、重试次数、退避系数、超时。
- `extra.list/detail`: 描述 JSON 结构，决定如何解析列表与详情。
- `field_map`: 详情 JSON 字段与 `JobRecord` 字段映射。
- `default_values`: 字段缺失时的回退值。
- `default_category_id`: 当数据库没有叶子分类时仍需写库的默认 DB 分类 ID。
- `default_api_category_id`: 与上项配对的接口分类 ID，可根据官网实际格式填写。
- `headers/list_headers/detail_headers`: 可选 HTTP 头，支持 `${ENV_VAR}`。

## 日志与增量策略
- HTTP 客户端自带节流及重试，若响应不是合法 JSON，会记录状态码与片段并重试。
- `JobCrawler` 会统计每个分类成功/失败数量，并在 `dry-run` 模式下只打印 SQL；常规模式始终执行增量写库，对已存在且无变化的职位仅刷新抓取元数据，避免重复写入。同时会自动比较分类的官方数量与已爬数量，必要时跳过；若检测到数据库条数多于本轮抓到的条数，会先清空旧职位再重新落库，并在最后回写 `official_job_count` 与 `crawled_job_count`。职位重新写入时，`job_id` 生成器会优先填补删除后留下的空缺编号，只有在没有可复用编号时才继续递增，避免长期运行后编号溢出。

## 常见问题
- **ModuleNotFoundError: crawler**：请确认从仓库根目录运行 `pytest` 或 `python main.py`，测试已在 `tests/conftest.py` 中处理路径。
- **分类缺失**：若数据库没有目标 `category_id`，确保 `rules` 中提供默认分类对；否则程序会抛出异常提醒配置。
- **JSON 解析失败**：日志会显示状态码和响应片段，可检查是否被 WAF/代理拦截或需要额外头信息。

## 测试

```bash
pytest
```

测试涵盖时间解析、分类兜底、HTTP JSON 失败重试等关键逻辑，建议在修改规则或核心代码后运行。

## 数据维护

- **批量重排旧职位ID**：当历史导入导致 `job.id` 出现空洞或顺序错乱时，使用 `rebuild_job_ids.py` 可同时满足“全量修复”和“定向修复”两种场景。

```bash
    python rebuild_job_ids.py --company-id C001 --dry-run --env-file .env
```

- 取消 `--dry-run` 即会真实写库；不指定 `--company-id` 会遍历 job 表里全部公司。还支持 `--limit` 仅处理前 N 条、`--preview` 控制日志示例长度、`--log-level` 自定义输出等级。脚本会先自动把 `job` 表完整备份到 `backups/` 目录：
  - **备份表命名**：`job_backup_YYYYMMDDHHMMSS_<随机>`，和原表结构一致，所有数据完整复制；
  - **SQL 文件**：同名 `.sql` 会写入两条语句（`CREATE TABLE` + `INSERT INTO ... SELECT * FROM job`），可直接手动执行恢复；
  - **恢复示例**：`mysql -u root -p job_system < backups/job_backup_20260325101530_ab12cd.sql` 或在 MySQL 控制台执行 `DROP TABLE job; RENAME TABLE job_backup_20260325101530_ab12cd TO job;`。
  - **快速找到最新备份**：在项目根目录执行 `Get-ChildItem backups -Filter 'job_backup_*.sql' | Sort-Object Name -Descending | Select-Object -First 1` 即可看到最新的 SQL 备份；在 MySQL 中可运行 `SELECT table_name, create_time FROM information_schema.tables WHERE table_schema='job_system' AND table_name LIKE 'job_backup_%' ORDER BY create_time DESC LIMIT 1;` 获取最新备份表名。
   完成备份后，脚本再把待更新记录改为临时 ID 并写回目标 ID，整个过程在单次事务内完成，若失败会回滚，确保原表与备份同时可用。
