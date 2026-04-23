from global_rewrite import rewrite_jobs
from main import get_detail

def zhaopin_process(post_id, location, job_url, job_type):
    """适配器：调用官网的 get_detail，返回是否成功"""
    return get_detail(job_type, post_id, location, job_url)

if __name__ == "__main__":
    rewrite_jobs(zhaopin_process)