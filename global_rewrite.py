import pymysql
from db_conn import connect_db

def rewrite_jobs(process_func, db_config=None):
    """
    通用补全空缺字段流程。

    参数:
        process_func: 函数，签名应为 func(post_id, location, job_url, job_type) -> bool
                     返回 True 表示补全成功，False 表示失败。
        db_config: 数据库连接配置，默认使用 connect_db()
    """
    if db_config is None:
        conn = connect_db()
        if conn is None:
            print("重爬时无法建立数据库连接，跳过")
            return False
    else:
        conn = pymysql.connect(**db_config)

    cursor = conn.cursor()
    try:
        sql = """
            SELECT post_id, location, job_url, job_type 
            FROM job 
            WHERE (description IS NULL OR description = '' 
                   OR requirement IS NULL OR requirement = '')
              AND is_deleted = 0
        """
        cursor.execute(sql)
        rows = cursor.fetchall()
        if not rows:
            print("没有发现 description 或 requirement 为空的职位")
            return 0

        success_count = 0
        for row in rows:
            post_id, location, job_url, job_type = row
            print(f"正在修复空缺职位: {job_url}")
            try:
                if process_func(post_id, location, job_url, job_type):
                    success_count += 1
                else:
                    print(f"修复失败: {job_url}")
            except Exception as e:
                print(f"处理异常 {job_url}: {e}")

        print(f"共处理 {len(rows)} 个空缺职位，成功修复 {success_count} 个")
        return success_count
    finally:
        cursor.close()
        conn.close()