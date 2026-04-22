import pymysql
import requests
import time
import re
from main import detail_url,extract_description_requirement

from dotenv import load_dotenv
import os

load_dotenv()  # 加载 .env 文件

DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME'),
    'charset': os.getenv('DB_CHARSET', 'utf8mb4')
}

def _extract_post_id(job_url):
    match = re.search(r'[?&]postId=(\d+)', job_url)
    return match.group(1) if match else None

#重爬
def _retry_single_job(job_url, db_config=None):
    """重新爬取单个职位；若岗位已下架则标记 is_deleted=1。"""
    if db_config is None:
        db_config = DB_CONFIG
    post_id = _extract_post_id(job_url)
    if not post_id:
        return False

    timestamp = int(time.time() * 1000)
    try:
        resp = requests.get(
            f"{detail_url}?timestamp={timestamp}&postId={post_id}",
            timeout=10
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as e:
        print(f"重爬失败 {job_url}: {e}")
        return False

    status = body.get("status")
    message = body.get("message", "")
    data = body.get("data")

    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()
    try:
        # 业务层返回岗位下架：直接软删除，避免后续重复重爬
        if status == 404 and data is None:
            sql = """
                UPDATE job
                SET is_deleted = 1, crawled_at = NOW()
                WHERE job_url = %s and is_deleted = 0
            """
            cursor.execute(sql, (job_url,))
            conn.commit()
            print(f"岗位已下架，已标记删除: {job_url} ({message})")
            return cursor.rowcount > 0

        if not isinstance(data, dict):
            data = {}

        description, requirement = extract_description_requirement(data)

        sql = """
            UPDATE job
            SET description = %s, requirement = %s, is_deleted = 0, crawled_at = NOW()
            WHERE job_url = %s
        """
        cursor.execute(sql, (description, requirement, job_url))
        conn.commit()
        print(f"重爬成功 {job_url}: {description}, {requirement}")
        return cursor.rowcount > 0
    except Exception as e:
        conn.rollback()
        print(f"写库失败 {job_url}: {e}")
        return False
    finally:
        cursor.close()
        conn.close()


def rewrite_jobs(db_config=None):
    """
    查询 job 表中 description 或 requirement 为空的职位，
    并逐个重新爬取以补全字段。
    """
    if db_config is None:
        db_config = DB_CONFIG

    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()
    try:
        # 注意字段名是 description，不是 decription
        sql = "SELECT job_url FROM job WHERE description IS NULL OR description = '' OR requirement IS NULL OR requirement = ''"
        cursor.execute(sql)
        rows = cursor.fetchall()
        if not rows:
            print("没有发现 description 或 requirement 为空的职位")
            return 0

        success_count = 0
        for row in rows:
            job_url = row[0]
            print(f"正在修复空缺职位: {job_url}")
            if _retry_single_job(job_url, db_config):
                success_count += 1
            else:
                print(f"修复失败: {job_url}")

        print(f"共处理 {len(rows)} 个空缺职位，成功修复 {success_count} 个")
        return success_count
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    rewrite_jobs()