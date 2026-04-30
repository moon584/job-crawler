from 腾讯.social import get_detail as _C001_social_get_detail
from 腾讯.campus import get_detail as _tencent_campus_get_detail
from 美团.main import get_detail as _meituan_get_detail
from 拼多多.campus import get_detail as _pdd_get_detail
from 阿里巴巴.campus import get_detail as _alibaba_get_detail
from 网易.intern_2 import get_detail as _netease_game_intern_get_detail

import pymysql
from db_conn import connect_db


# ---------- 公司分发表 ----------
# (company_id, job_type) -> handler

_DISPATCH = {
    # 腾讯社招
    ("C001", 0): _C001_social_get_detail,
    # 腾讯校招/实习
    ("C001", 1): _tencent_campus_get_detail,
    ("C001", 2): _tencent_campus_get_detail,
    # 美团（所有类型）
    ("C007", 0): _meituan_get_detail,
    ("C007", 1): _meituan_get_detail,
    ("C007", 2): _meituan_get_detail,
    # 拼多多
    ("C008", 1): _pdd_get_detail,
    ("C008", 2): _pdd_get_detail,
    # 阿里巴巴（仅实习）
    ("C002", 2): _alibaba_get_detail,
    # 网易游戏互娱（仅实习）
    ("C005", 2): _netease_game_intern_get_detail,
}


# ---------- 通用补全流程 ----------

def rewrite_jobs(process_func=None, db_config=None, company_id=None, job_type=None):
    """
    通用补全空缺字段流程。

    参数:
        process_func: 处理函数，签名 (post_id, location, job_url, job_type) -> bool
                      为 None 时自动根据 company_id 分发
        db_config:    数据库连接配置，默认使用 connect_db()
        company_id:   可选，仅修复指定公司
        job_type:     可选，仅修复指定类型，接受 int 或 list/tuple
    """
    if db_config is None:
        conn = connect_db()
    else:
        conn = pymysql.connect(**db_config)
    if conn is None:
        print("重爬时无法建立数据库连接，跳过")
        return False

    cursor = conn.cursor()
    try:
        conditions = [
            "(description IS NULL OR description = '' "
            "OR requirement IS NULL OR requirement = '')",
            "is_deleted = 0",
        ]
        params = []
        if company_id is not None:
            conditions.append("company_id = %s")
            params.append(company_id)
            if job_type is not None:
                if isinstance(job_type, (list, tuple)):
                    placeholders = ", ".join(["%s"] * len(job_type))
                    conditions.append(f"job_type IN ({placeholders})")
                    params.extend(job_type)
                else:
                    conditions.append("job_type = %s")
                    params.append(job_type)

        sql = (
            "SELECT post_id, location, job_url, job_type, company_id "
            f"FROM job WHERE {' AND '.join(conditions)}"
        )
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        if not rows:
            print("没有发现 description 或 requirement 为空的职位")
            return 0

        success_count = 0
        for row in rows:
            post_id, location, job_url, row_job_type, row_company_id = row
            print(f"正在修复空缺职位 [{row_company_id}]: {job_url}")
            print(f"  -> 请求详情 API ...")

            func = process_func or _DISPATCH.get((row_company_id, row_job_type))
            if func is None:
                print(f"  -> 跳过，无对应处理函数: company_id={row_company_id}")
                continue

            try:
                if func(post_id, location, job_url, row_job_type):
                    success_count += 1
                else:
                    print(f"  -> 修复失败: {job_url}")
            except Exception as e:
                print(f"  -> 处理异常 {job_url}: {e}")

        print(f"共处理 {len(rows)} 个空缺职位，成功修复 {success_count} 个")
        return success_count
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    rewrite_jobs()
