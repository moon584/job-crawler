# db_conn.py
# 统一的数据库连接模块：从环境变量读取配置并尝试建立连接。
from dotenv import load_dotenv, find_dotenv
import os
import pymysql

# 在运行时（模块导入时）尝试寻找并加载 .env 文件（若存在）
load_dotenv(find_dotenv())

def get_db_config():
    """
    从环境变量读取 DB_* 配置并返回字典。
    若缺少必须项（DB_USER/DB_PASSWORD）会抛出 RuntimeError。
    """
    host = os.getenv('DB_HOST', 'localhost')
    port_str = os.getenv('DB_PORT', '3306')
    try:
        port = int(port_str)
    except Exception:
        raise ValueError(f"无效的 DB_PORT 值: {port_str}")

    user = os.getenv('DB_USER')
    password = os.getenv('DB_PASSWORD')
    database = os.getenv('DB_NAME', 'job')
    charset = os.getenv('DB_CHARSET', 'utf8mb4')

    missing = []
    if not user:
        missing.append('DB_USER')
    if not password:
        missing.append('DB_PASSWORD')
    if missing:
        raise RuntimeError(f"缺少环境变量: {', '.join(missing)}")

    return {
        'host': host,
        'port': port,
        'user': user,
        'password': password,
        'database': database,
        'charset': charset,
    }

def connect_db():
    """
    尝试建立数据库连接：
    - 成功时打印 "数据库连接成功" 并返回连接对象
    - 失败时打印 "数据库连接失败: <错误信息>" 并返回 None
    """
    try:
        cfg = get_db_config()
    except Exception as e:
        print(f"数据库连接失败: {e}")
        return None

    try:
        conn = pymysql.connect(**cfg)
        print("数据库连接成功")
        return conn
    except Exception as e:
        print("数据库连接失败:", e)
        return None

