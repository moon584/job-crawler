import pymysql
import requests
import time
import re
from main import detail_url, extract_description_requirement
from db_conn import connect_db

# ----------------------------------------------------------------------------
# 说明：用于补爬 `job` 表中缺失 `description` 或 `requirement` 的记录。
# - `rewrite_jobs` 会扫描数据库中 description/requirement 为空的 job_url 列表，
#   然后调用 `_retry_single_job` 逐条重新请求详情并回写数据库。
# 实习软删除功能
# - `_retry_single_job` 在无法连接数据库时会返回 False 并打印提示。
# ----------------------------------------------------------------------------

def _extract_post_id(job_url):
    """
    从 job_url 中提取 postId 参数的数字值，返回字符串或者 None。
    例如：`https://.../post_detail.html?postId=12345` -> 返回 '12345'
    """
    match = re.search(r'[?&]postId=(\d+)', job_url)
    return match.group(1) if match else None

#重爬
def _retry_single_job(job_url, db_config=None):
    """
    重新爬取并更新单个职位的 description 与 requirement。

    参数：
    - job_url: 职位详情页面的 URL
    - db_config: 可选数据库配置字典；若为 None 则使用 db_conn.connect_db() 建立连接

    行为：
    - 若页面返回 status == 404 且 data 为 None，则将该职位标记为 is_deleted=1
    - 否则提取 description/requirement 并写回数据库
    - 返回 True 表示写库成功并影响行数 > 0，返回 False 表示失败
    """
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
        conn = connect_db()
        if conn is None:
            print("重爬时无法建立数据库连接，跳过")
            return False
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