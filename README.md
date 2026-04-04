# 招聘官网爬虫框架

用于按公司分类抓取各大招聘官网岗位信息，支持配置化与代码级扩展、增量写库及软删除数据同步。

## 核心特性
- **支持四大类爬虫模式**：
  - **基于配置的 JSON 爬虫 (ConfigProvider)**：通过在 `rules/company.json` 配置路径映射即可接入接口简单的官网（如腾讯）。
  - **定制 API 爬虫 (CustomApiProvider)**：支持编写 Python 代码接管加密、签名、动态字段重组（如美团），支持复用底层节流和入库逻辑。
  - **基于 HTML 的爬虫 (HtmlProvider)**：对于只返回 HTML 网页的传统系统，使用 BeautifulSoup/lxml 解析。
  - **动态爬虫 (DynamicProvider)**：支持通过无头浏览器抓取复杂反爬系统（预留）。
- **智能增量更新与软删除**：
  - 快爬（Fast）模式下，通过最新发布时间或唯一链接 (`job_url`) 增量获取，新岗位直接入库。
  - 慢爬（Slow）模式下，针对官网下架岗位提供“按次同步删除”的机制。不论是快爬发现分类数量超出还是慢爬收尾，框架均不再直接硬删数据，而是对比本次爬取的开始时间 `crawled_at` 与旧数据，将未碰到的下架岗位软删（`is_deleted=1`）。只有运行专用清理脚本时，才会进行物理删除。
- **全量字段比对与更新**：
  - 在遇到数据库已存在的岗位（`job_url` 相同）时，框架不再无脑跳过，而是将官网最新提取的职位要求、描述、地点、薪资等所有核心字段与数据库内记录进行比对。
  - 若内容有变，只提取变化字段生成 `UPDATE` 语句并更新 `crawled_at`；若完全无变动，则仅刷新存活时间，极大降低数据库写入压力。
- **自动恢复认证 (Auth Refresh)**：内置 `AuthError` 异常捕捉，一旦检测到 Cookie/Token 过期，框架可触发爬虫自带的登录刷新动作，成功后自动重试刚失败的接口，彻底防止抓到一半断网或被踢。
## 快速上手顺序
1. **配置数据库**：执行 `sql.sql` 初始化结构，确保 `company/category/job` 三表可用。
2. **配置环境变量**：创建 `.env` 并写入数据库连接信息。
3. **准备规则 JSON**：在 `rules/company.json` 为目标公司新增配置，可直接复制示例条目，也可以完全删除示例自行编写。
4. **安装依赖并运行**：安装 `requirements.txt`，随后执行 `python main.py` 完成交互式抓取。
5. **按需维护**：使用 Web/TUI 编辑器调整规则或运行重排脚本维护历史数据。

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
- **配置数据库**
  - 执行 `sql.sql`，初始化 `company/category/job` 结构与索引；首次使用可在 `category` 中填充叶子分类与 `categoryid`。
  - 若已有历史数据，提前备份并确保 `categoryid` 与目标官网分类 ID 一一对应。

- **配置环境变量**
  - 复制 `.env.example` 为 `.env`，并写入数据库地址/端口/凭据。
  - 支持直接通过系统环境变量覆盖，下表给出了所有必填项：

| 变量名        | 说明                       | 默认值 |
|---------------|----------------------------|--------|
| `DB_HOST`     | MySQL 地址                 | 127.0.0.1 |
| `DB_PORT`     | MySQL 端口                 | 3306 |
| `DB_USER`     | 数据库用户名               | root |
| `DB_PASSWORD` | 数据库密码                 | （空） |
| `DB_NAME`     | 数据库名称                 | job_system |

- **准备规则文件**
  - `rules/company.json` 管理全部公司配置。可直接复制示例条目接入新官网；若不需要示例，也可以删除或替换为自己的配置。
  - `extra.default_category_id` 与 `extra.default_api_category_id` 需成对设置，用于无叶子分类场景。

- **安装依赖**

```bash
pip install -r requirements.txt
```

完成以上配置后，可进入“运行方式”一节按提示启动爬虫。

## 运行方式

```bash
python main.py --rules rules/company.json [--env-file .env] [--dry-run]
```

运行时交互步骤：
1. 输入公司 ID（如 `C001`）。
2. 选择招聘类型：`0` 社会招聘，`1` 校园招聘。
3. 选择爬取模式：`fast` 快爬，`slow` 慢爬。
4. 输入要抓取的分类 ID，逗号分隔或输入 `all` 全部分类。
5. 输入每个分类抓取条数，数字或 `all`。
6. `fast` 模式会按官网分类数量判定是否可跳过（超量数据会被标记为待删除 `is_deleted=1`）。`slow` 模式会以本次脚本启动的时间为准，在抓取结束时把没有遇到过的职位标记为 `is_deleted=1`（软删下架岗位）。系统会统计并提示有多少 `is_deleted=1` 的旧岗位，你可以通过专门的清理脚本集中硬删除。

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
  "list_api": { "url": "https://...", "method": "POST", "default_params": { ... } },
  "detail_api": { "url": "https://...", "method": "GET", "default_params": { ... } },
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

- `list_api/detail_api`: 接口地址、默认参数、可选 `method`（缺省为 `GET`，填 `POST` 时会自动以 JSON body 提交请求）。
- `throttle`: 每次请求的最小/最大延迟、重试次数、退避系数、超时。
- `extra.list/detail`: 描述 JSON 结构，决定如何解析列表与详情。
- `field_map`: 详情 JSON 字段与 `JobRecord` 字段映射。
- `default_values`: 字段缺失时的回退值。
- `default_category_id`: 当数据库没有叶子分类时仍需写库的默认 DB 分类 ID。
- `default_api_category_id`: 与上项配对的接口分类 ID，可根据官网实际格式填写。
- `auto_category_mode`: 可选布尔值，开启后列表接口只请求一次，由 `category_rules` 自动将岗位归入不同分类，适用于像美团这样列表已有“岗位家族”字段的官网。
- `category_rules`: 自动分类模式的匹配表，列表/详情 JSON 路径 → 分类 ID，可用字符串或数组匹配多个值；记得在数据库 `category` 表预先创建对应 `category_id`。
- `job_type_overrides`: 以 `{"0": {...}, "1": {...}}` 形式为不同 `job_type` 指定专属 `list_api`/`detail_api`/`extra` 覆盖项（例如社招与校招接口、详情页模板不同）。若用户在 CLI 中输入对应 job_type，程序会自动套用这些覆盖配置。
- `skip_detail_if_exists`: 可选布尔值，默认 `true`。开启时会在详情请求前根据列表项预测 `job_url`，若数据库已存在则直接跳过该职位，减少详情接口请求。
- `headers/list_headers/detail_headers`: 可选 HTTP 头，支持 `${ENV_VAR}`。
- `url_templates`: 可选模板，当前支持 `job_url`，可用 `{字段名}` 引用详情 JSON 字段（例如 `https://xxx/detail?id={jobUnionId}`）。
- **示例条目说明**：`rules/company.json` 中的示例公司对象（`company_id` 为 `CXXX`）仅用于演示 JSON 结构，字段含义如下，可复制后编辑；若不需要也可以删除：
  - `list_api/detail_api`：演示如何填写默认参数与接口地址；
  - `throttle`：提供一个限流模板，可按需放宽或收紧；
  - `extra.list/detail`：展示 JSON 路径写法（含列表、嵌套字段）；
  - `field_map/default_values`：说明如何绑定字段和提供兜底值；
  - 你可以将其复制为新条目，修改 `company_id`、接口地址等信息，也可以直接删除示例，仅保留真实配置。

## 日志与增量策略
- HTTP 客户端自带节流及重试，若响应不是合法 JSON，会记录状态码与片段并重试。
- `JobCrawler` 会统计每个分类成功/失败数量，并在 `dry-run` 模式下只打印变化日志而不写库。遇到已存在的 `job_url` 岗位时，框架会**对比**所有字段：如果有变化（如职位薪水/要求修改）则更新数据并刷新 `crawled_at`；如果无变化，仅更新时间。
- 对于下架职位（即数据库原本有，但本次爬虫开始到结束始终没碰到过的职位），程序会在爬取收尾阶段将其标记为 `is_deleted=1`，而**绝不硬删除**。请定期在确认本次全量爬取数据无误后，手动运行清理脚本以保持数据库整洁。

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

- **清理软删除岗位**：任何因下架或分类变更而被标记为 `is_deleted=1` 的数据不会自动硬删，需手动执行（或在爬虫运行结束后根据交互提示执行）：
  ```bash
  python tools/clean_deleted_jobs.py --company C007  # 删除 C007 的软删记录
  python tools/clean_deleted_jobs.py                 # 全量清理所有废弃记录
  ```
  加上 `--dry-run` 则只统计条数。

- **规则可视化编辑（Web）**：运行内置 Flask 服务即可在浏览器中编辑 `rules/company.json`，支持实时校验与保存。

```bash
python tools/rules_frontend_server.py --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/` 后即可查看规则列表、编辑字段或新增规则，保存时会触发 JSON Schema 校验并同步到文件。

> 📌 **美团（company_id = C007）接入说明**：默认以 `auto_category_mode` 拉取全量岗位，并根据 `jobFamily`/`jobFamilyGroup` 自动分类。你只需在数据库 `category` 表补齐 `C007DEFAULT` 及 `category_rules` 中列出的 `category_id`，后续若要拓展分类，新增规则即可，无需再改代码。

> 📌 **腾讯校招（company_id = C001, job_type = 1）接入说明**：利用 `job_type_overrides` 配置特性，同一公司不同招聘类型可分别使用不同 API 与分类映射。腾讯校招启用了自动分类 (`auto_category_mode=true`)，基于返回的 `projectId` 分流。数据库需预先写入对应类目。

- **规则校验**：修改 `rules/company.json` 后，建议先通过 Schema 校验快速发现缺失字段或格式问题。

```bash
python tools/validate_rules.py --rules rules/company.json --schema rules/company.schema.json
```

- **批量重排旧职位ID**：当历史导入导致 `job.id` 出现空洞或顺序错乱时，使用 `tools/rebuild_job_ids.py` 可同时满足“全量修复”和“定向修复”两种场景。

```bash
    python tools/rebuild_job_ids.py --company-id C001 --dry-run --env-file .env
```

- 取消 `--dry-run` 即会真实写库；不指定 `--company-id` 会遍历 job 表里全部公司。还支持 `--limit` 仅处理前 N 条、`--preview` 控制日志示例长度、`--log-level` 自定义输出等级。脚本会先自动把 `job` 表完整备份到 `backups/` 目录：
  - **备份表命名**：`job_backup_YYYYMMDDHHMMSS_<随机>`，和原表结构一致，所有数据完整复制；
  - **SQL 文件**：同名 `.sql` 会写入两条语句（`CREATE TABLE` + `INSERT INTO ... SELECT * FROM job`），可直接手动执行恢复；
  - **恢复示例**：`mysql -u root -p job_system < backups/job_backup_20260325101530_ab12cd.sql` 或在 MySQL 控制台执行 `DROP TABLE job; RENAME TABLE job_backup_20260325101530_ab12cd TO job;`。
  - **快速找到最新备份**：在项目根目录执行 `Get-ChildItem backups -Filter 'job_backup_*.sql' | Sort-Object Name -Descending | Select-Object -First 1` 即可看到最新的 SQL 备份；在 MySQL 中可运行 `SELECT table_name, create_time FROM information_schema.tables WHERE table_schema='job_system' AND table_name LIKE 'job_backup_%' ORDER BY create_time DESC LIMIT 1;` 获取最新备份表名。
   完成备份后，脚本再把待更新记录改为临时 ID 并写回目标 ID，整个过程在单次事务内完成，若失败会回滚，确保原表与备份同时可用。
