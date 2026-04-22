"""
test_conn.py
简单测试：尝试通过 db_conn.connect_db() 建立连接并关闭，输出结果。
"""
from db_conn import connect_db

def main():
    conn = connect_db()
    if conn:
        try:
            conn.close()
        except Exception:
            pass
        print("测试：连接并关闭成功")
    else:
        print("测试：无法建立连接")

if __name__ == '__main__':
    main()

