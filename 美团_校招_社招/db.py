import pymysql

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
#存入数据库的函数
def save_to_database(table_name, columns, data_tuple, unique_key, db_config=None):
    if db_config is None:
        db_config = DB_CONFIG

    if len(columns) != len(data_tuple):
        raise ValueError("字段数量与值数量不匹配")

    try:
        key_index = columns.index(unique_key)
    except ValueError:
        raise ValueError(f"唯一键 {unique_key} 不在 columns 列表中")

    key_value = data_tuple[key_index]

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