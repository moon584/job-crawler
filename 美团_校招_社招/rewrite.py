import pymysql
import requests
import time
import re
from main import detail_url,extract_description_requirement
from db_conn import connect_db

#数据库没有异常缺失值，所以没有改这个文件

def _extract_post_id(job_url):
    match = re.search(r'[?&]postId=(\d+)', job_url)
    return match.group(1) if match else None

#重爬
def _retry_single_job(job_url, db_config=None):
    """重新爬取单个职位，更新 description, requirement, crawled_at"""
    if db_config is None:
        conn = connect_db()
        if conn is None:
            print("重爬时无法建立数据库连接，跳过")
            return False
    else:
        conn = pymysql.connect(**db_config)
    post_id = _extract_post_id(job_url)
    if not post_id:
        return False

    timestamp = int(time.time() * 1000)
    try:
        resp = requests.get(f"{detail_url}?timestamp={timestamp}&postId={post_id}", timeout=10)
        data = resp.json().get("data", {})
        description,requirement= extract_description_requirement(data)
    except Exception as e:
        print(f"重爬失败 {job_url}: {e}")
        return False
    print(f"重爬成功 {job_url}: {description}, {requirement}")
    cursor = conn.cursor()
    try:
        sql = """
            UPDATE job 
            SET description = %s, requirement = %s, crawled_at = NOW()
            WHERE job_url = %s
        """
        cursor.execute(sql, (description, requirement, job_url))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()


def rewrite_jobs(db_config=None):
    """
    查询 job 表中 description 或 requirement 为空的职位，
    并逐个重新爬取以补全字段。
    """
    # 根据是否传入 db_config 获取连接
    if db_config is None:
        conn = connect_db()
        if conn is None:
            print("无法建立数据库连接，停止重爬任务")
            return 0
    else:
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