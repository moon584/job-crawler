"""
网易实习生招聘统一入口
依次爬取主站、互娱、雷火三个子站，全部完成后统一做过期检查
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中，支持直接运行 python 网易/__init__.py
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from datetime import datetime

from global_main import get_user_pagination, get_max_items, search_expired_job
from 网易.intern_1 import run_crawl as crawl_intern_1
from 网易.intern_2 import run_crawl as crawl_intern_2
from 网易.intern_3 import run_crawl as crawl_intern_3

CRAWLERS = [
    ("网易主站（hr.163.com）", crawl_intern_1),
    ("网易互娱（campus.game.163.com）", crawl_intern_2),
    ("网易雷火（xiaozhao.leihuo.netease.com）", crawl_intern_3),
]


def main():
    start_page, page_size = get_user_pagination()
    max_items = get_max_items()
    start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    total_saved = 0
    total_fetched = 0
    all_completed = True

    for name, crawl_func in CRAWLERS:
        print(f"\n{'='*40}")
        print(f"开始爬取：{name}")
        print(f"{'='*40}")
        saved, fetched, completed = crawl_func(start_page, page_size, max_items)
        total_saved += saved
        total_fetched += fetched
        if not completed:
            all_completed = False
        print(f"{name} 完成：保存 {saved} 个，获取 {fetched} 个")

    print(f"\n{'='*40}")
    print(f"网易实习全部爬取完成，共保存 {total_saved} 个职位")
    if all_completed and total_fetched > 0:
        search_expired_job("C005", 2, start_time)
    else:
        print("未完整爬取全量数据，跳过过期检查")


if __name__ == "__main__":
    main()
