# db.py (MySQL版本，先判断后插入或更新)
import pymysql
from db_conn import connect_db

# 说明：此模块负责把爬取到的数据写入 MySQL。实现策略为按唯一键去重：
# - 若记录存在（按 unique_key 检查）则执行 UPDATE
# - 否则执行 INSERT
#
# 设计要点：
# - 不在模块导入时立即建立数据库连接，避免导入即抛错。
# - 提供可选参数 db_config（字典），若传入则使用该配置连接数据库，便于测试或外部调用。


# 存入数据库的函数
def save_to_database(table_name, columns, data_tuple, unique_key, db_config=None):
    """
    将一条记录插入或更新到指定表。

    参数说明：
    - table_name: 表名（字符串）
    - columns: 列名列表（按顺序，对应 data_tuple）
    - data_tuple: 值的元组（顺序必须与 columns 对应）
    - unique_key: 用于去重的唯一键名（例如 'job_url'）
    - db_config: 可选的数据库连接配置字典（若不提供则使用 db_conn.connect_db() 建立连接）

    行为：当 db_config=None 时，会调用 connect_db() 建立连接；若失败会抛出 RuntimeError。
    """
    if len(columns) != len(data_tuple):
        raise ValueError("字段数量与值数量不匹配")

    try:
        key_index = columns.index(unique_key)
    except ValueError:
        raise ValueError(f"唯一键 {unique_key} 不在 columns 列表中")

    key_value = data_tuple[key_index]

    # 根据是否传入 db_config 获取连接
    if db_config is None:
        conn = connect_db()
        if conn is None:
            raise RuntimeError("无法建立数据库连接（请检查环境变量）")
    else:
        conn = pymysql.connect(**db_config)
    cursor = conn.cursor()
    try:
        # 查询是否存在
        check_sql = f"SELECT 1 FROM `{table_name}` WHERE `{unique_key}` = %s LIMIT 1"
        cursor.execute(check_sql, (key_value,))
        exists = cursor.fetchone() is not None

        if exists:
            # 更新
            set_clause = ', '.join([f"`{col}` = %s" for col in columns if col != unique_key])
            update_sql = f"UPDATE `{table_name}` SET {set_clause}, `is_deleted` = 0 WHERE `{unique_key}` = %s"
            update_values = [data_tuple[i] for i in range(len(columns)) if columns[i] != unique_key]
            update_values.append(key_value)
            cursor.execute(update_sql, update_values)
            print(f"更新记录: {unique_key}={key_value}")
        else:
            # 插入
            placeholders = ', '.join(['%s'] * len(columns))
            columns_str = ', '.join([f'`{col}`' for col in columns])
            insert_sql = f"INSERT INTO `{table_name}` ({columns_str}) VALUES ({placeholders})"
            cursor.execute(insert_sql, data_tuple)
            print(f"插入新记录: {unique_key}={key_value}")

        conn.commit()
    except Exception:
        conn.rollback()   # 可选：出错时回滚
        raise
    finally:
        cursor.close()
        conn.close()
    #print(f"数据: {data_tuple}")

def search_expired_job(company_id, job_type, start_time, db_config=None):
    """
    软删除过期的职位记录，并返回被删除的数量。

    """
    conn = None
    try:
        # 建立连接
        if db_config is None:
            conn = connect_db()
            if conn is None:
                raise RuntimeError("无法建立数据库连接（请检查环境变量）")
        else:
            conn = pymysql.connect(**db_config)

        cursor = conn.cursor()

        # 执行软删除
        update_sql = """
                     UPDATE `job`
                     SET `is_deleted` = 1
                     WHERE `company_id` = %s
                       AND `job_type` = %s
                       AND `crawled_at` < %s
                       AND `is_deleted` = 0 
                     """
        cursor.execute(update_sql, (company_id, job_type, start_time))

        # 获取受影响的行数
        deleted_count = cursor.rowcount

        # 提交事务
        conn.commit()

        # 输出删除数量（可根据需求改为 logging 或直接返回）
        print(f"已软删除 {deleted_count} 条过期职位记录")

    except Exception as e:
        if conn:
            conn.rollback()
        print(f"软删除失败: {e}")
        raise
    finally:
        if conn:
            conn.close()
