import pymysql
from pathlib import Path
from pymysql.cursors import DictCursor

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "12345678",
    "database": "job_recruitment",
    "charset": "utf8mb4",
}

TEXT_TYPES = {"char", "varchar", "text", "tinytext", "mediumtext", "longtext"}


def get_connection():
    return pymysql.connect(cursorclass=DictCursor, **DB_CONFIG)


def fetch_job_columns(cursor):
    sql = """
    SELECT COLUMN_NAME, DATA_TYPE
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'job'
    ORDER BY ORDINAL_POSITION
    """
    cursor.execute(sql, (DB_CONFIG["database"],))
    return cursor.fetchall()


def build_empty_count_sql(job_columns):
    empty_count_parts = []
    for col in job_columns:
        col_name = col["COLUMN_NAME"]
        data_type = (col["DATA_TYPE"] or "").lower()

        if data_type in TEXT_TYPES:
            cond = f"(j.`{col_name}` IS NULL OR TRIM(j.`{col_name}`) = '')"
        else:
            cond = f"(j.`{col_name}` IS NULL)"

        empty_count_parts.append(
            f"SUM(CASE WHEN {cond} THEN 1 ELSE 0 END) AS `empty_{col_name}`"
        )

    return ",\n        ".join(empty_count_parts)


def fetch_group_stats(cursor, empty_count_sql):
    sql = f"""
    SELECT
        j.company_id,
        COALESCE(c.name, 'UNKNOWN_COMPANY') AS company_name,
        CASE
            WHEN j.job_type = 0 THEN '社招'
            WHEN j.job_type = 1 THEN '校招'
            ELSE '未知'
        END AS recruit_type,
        COUNT(*) AS total_jobs,
        SUM(CASE WHEN j.is_deleted = 1 THEN 1 ELSE 0 END) AS pending_delete_jobs,
        {empty_count_sql}
    FROM job j
    LEFT JOIN company c ON c.id = j.company_id
    GROUP BY
        j.company_id,
        COALESCE(c.name, 'UNKNOWN_COMPANY'),
        CASE
            WHEN j.job_type = 0 THEN '社招'
            WHEN j.job_type = 1 THEN '校招'
            ELSE '未知'
        END
    ORDER BY
        company_name,
        FIELD(recruit_type, '社招', '校招', '未知')
    """
    cursor.execute(sql)
    return cursor.fetchall()


def fetch_overview(cursor):
    sql = """
    SELECT
        COUNT(*) AS total_jobs,
        SUM(CASE WHEN is_deleted = 1 THEN 1 ELSE 0 END) AS pending_delete_jobs,
        SUM(CASE WHEN job_type = 0 THEN 1 ELSE 0 END) AS total_social,
        SUM(CASE WHEN job_type = 1 THEN 1 ELSE 0 END) AS total_campus,
        SUM(CASE WHEN job_type IS NULL OR job_type NOT IN (0, 1) THEN 1 ELSE 0 END) AS total_unknown
    FROM job
    """
    cursor.execute(sql)
    return cursor.fetchone()


def build_report_text(overview, rows, job_columns):
    recruit_types = ["社招", "校招", "未知"]
    empty_fields = [f"empty_{col['COLUMN_NAME']}" for col in job_columns]

    company_map = {}
    for row in rows:
        key = (row["company_id"], row["company_name"])
        company_map.setdefault(key, {})[row["recruit_type"]] = row

    lines = []
    lines.append("# job 表统计报告")
    lines.append("")
    lines.append("## 总览")
    lines.append("")
    lines.append("| 总职位 | 待删除 | 社招 | 校招 | 未知 |")
    lines.append("|:---:|:---:|:---:|:---:|:---:|")
    lines.append(
        f"| {overview['total_jobs']} | {overview['pending_delete_jobs']} | "
        f"{overview['total_social']} | {overview['total_campus']} | {overview['total_unknown']} |"
    )

    if not rows:
        lines.append("")
        lines.append("job 表暂无数据。")
        return "\n".join(lines)

    lines.append("")
    lines.append("## 按公司统计")

    for (company_id, company_name), type_map in sorted(company_map.items(), key=lambda x: x[0][1]):
        safe_company_name = (company_name or "UNKNOWN_COMPANY").replace("|", "\\|")
        lines.append("")
        lines.append(f"### {safe_company_name} ({company_id})")
        lines.append("")
        lines.append("| 指标 | 社招 | 校招 | 未知 |")
        lines.append("|:---:|:---:|:---:|:---:|")

        lines.append(
            "| 总职位数 | "
            + " | ".join(str(type_map.get(t, {}).get("total_jobs", 0)) for t in recruit_types)
            + " |"
        )
        lines.append(
            "| 待删除职位数 | "
            + " | ".join(str(type_map.get(t, {}).get("pending_delete_jobs", 0)) for t in recruit_types)
            + " |"
        )

        for field_alias in empty_fields:
            field_name = field_alias.replace("empty_", "", 1)
            lines.append(
                f"| {field_name} 空值 | "
                + " | ".join(str(type_map.get(t, {}).get(field_alias, 0)) for t in recruit_types)
                + " |"
            )

    return "\n".join(lines)


def write_report(report_text, output_path):
    output_path.write_text(report_text, encoding="utf-8")


def main():
    conn = None
    output_path = Path(__file__).with_name("check_db_report.md")
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            job_columns = fetch_job_columns(cursor)
            if not job_columns:
                print("未找到 job 表字段，请检查数据库或表名。")
                return

            empty_count_sql = build_empty_count_sql(job_columns)
            overview = fetch_overview(cursor)
            rows = fetch_group_stats(cursor, empty_count_sql)
            report_text = build_report_text(overview, rows, job_columns)
            write_report(report_text, output_path)
            print(f"报告已写入（覆盖模式）: {output_path}")

    except pymysql.MySQLError as exc:
        print(f"数据库错误: {exc}")
    except Exception as exc:
        print(f"运行失败: {exc}")
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
