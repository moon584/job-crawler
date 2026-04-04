import argparse
import logging
import sys

from crawler.config import Settings
from crawler.db import Database

def parse_args():
    parser = argparse.ArgumentParser(description="删除已被标记(is_deleted=1)的下架职位。")
    parser.add_argument("--env-file", default=None, help="Optional path to .env file")
    parser.add_argument("--company", default=None, help="指定公司ID进行清理（如 C001），不指定则清理全库废弃岗位")
    parser.add_argument("--dry-run", action="store_true", help="仅统计，不执行删除")
    return parser.parse_args()

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stdout
    )
    args = parse_args()
    settings = Settings.from_env(args.env_file)
    db = Database(settings)

    with db.cursor() as cur:
        if args.company:
            cur.execute("SELECT COUNT(*) as total FROM job WHERE is_deleted=1 AND company_id=%s", (args.company,))
            total = cur.fetchone()["total"]
        else:
            cur.execute("SELECT COUNT(*) as total FROM job WHERE is_deleted=1")
            total = cur.fetchone()["total"]

        if total == 0:
            logging.info("没有找到 is_deleted=1 的记录，无需清理。")
            return

        if args.dry_run:
            logging.info("[DRY-RUN] 如果执行，将彻底删除 %d 条废弃岗位。", total)
            return

        logging.warning("即将删除 %d 条记录...", total)
        if args.company:
            cur.execute("DELETE FROM job WHERE is_deleted=1 AND company_id=%s", (args.company,))
        else:
            cur.execute("DELETE FROM job WHERE is_deleted=1")

        deleted = cur.rowcount
        logging.info("成功删除了 %d 条下架岗位！", deleted)

if __name__ == "__main__":
    main()
