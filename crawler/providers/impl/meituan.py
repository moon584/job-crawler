from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from crawler.models import JobRecord
from crawler.providers.base import BaseProvider, ListResult, AuthError
from crawler.utils import parse_publish_time


class MeituanProvider(BaseProvider):
    """美团定制爬虫。

    美团因为存在校园招聘和社会招聘使用不同的接口及不同的参数格式，
    同时在 JSON 中直接配置过于繁琐，因此在此处使用 Python 原生实现。
    """

    def __init__(self, rule, http_client=None) -> None:
        super().__init__(rule, http_client)
        self.extra = rule.extra
        self._list_headers = self.extra.get("list_headers", {})
        self._detail_headers = self.extra.get("detail_headers", {})
        self._warmup_urls = self.extra.get("warmup_urls", ["https://zhaopin.meituan.com/web/social"])
        self._default_api_category_id = self.extra.get("default_api_category_id", "MEITUAN_ALL")
        self._default_category_id = self.extra.get("default_category_id", "C007DEFAULT")
        self._category_rules = self.extra.get("category_rules", [])

    def list_headers(self) -> Optional[Dict[str, str]]:
        if self.job_type == 1:
            return self.extra.get("job_type_overrides", {}).get("1", {}).get("extra", {}).get("list_headers", self._list_headers)
        return self._list_headers

    def detail_headers(self) -> Optional[Dict[str, str]]:
        if self.job_type == 1:
            return self.extra.get("job_type_overrides", {}).get("1", {}).get("extra", {}).get("detail_headers", self._detail_headers)
        return self._detail_headers

    def warmup_urls(self) -> List[str]:
        if self.job_type == 1:
            return self.extra.get("job_type_overrides", {}).get("1", {}).get("extra", {}).get("warmup_urls", ["https://zhaopin.meituan.com/web/campus"])
        return self._warmup_urls

    def build_list_params(self, category_id: str, page: int) -> Dict[str, Any]:
        # 美团社招和校招的列表接口参数可能有区别，根据 job_type_overrides 加载
        default_params = self.list_endpoint.default_params
        if self.job_type == 1:
            override_params = self.extra.get("job_type_overrides", {}).get("1", {}).get("list_api", {}).get("default_params", {})
            params = dict(override_params) if override_params else dict(default_params)
        else:
            params = dict(default_params)

        # 美团的分页参数通常嵌套在 page 对象里
        if "page" in params:
            params["page"]["pageNo"] = page
        else:
            params["page"] = {"pageNo": page, "pageSize": 10}
        return params

    def parse_list_response(self, payload: Dict[str, Any], page: int) -> ListResult:
        status = payload.get("status")
        # 假设美团接口中 status == 401 意味着未登录/会话过期 (示例)
        if status == 401:
            raise AuthError("美团列表接口返回 401 未授权，可能需要刷新 Cookie")

        if status not in (0, 1):
            raise RuntimeError(f"美团列表接口返回异常: status={status}")

        data = payload.get("data", {})
        posts = data.get("list", [])

        # 获取总数
        total_count = None
        if "page" in data:
            total_count = data["page"].get("totalCount")

        page_size = 10
        has_more = bool(posts) and (
            (total_count is not None and page * page_size < total_count)
            or (total_count is None and len(posts) == page_size)
        )
        return ListResult(posts=posts, total_count=total_count, has_more=has_more)

    def extract_post_id(self, post: Dict[str, Any]) -> Optional[str]:
        return str(post.get("jobUnionId", "")).strip() or None

    def predict_job_url(self, post: Dict[str, Any]) -> Optional[str]:
        job_union_id = self.extract_post_id(post)
        if not job_union_id:
            return None
        highlight_type = "campus" if self.job_type == 1 else "social"
        return f"https://zhaopin.meituan.com/web/position/detail?jobUnionId={job_union_id}&highlightType={highlight_type}"

    def build_detail_params(self, post_id: str) -> Dict[str, Any]:
        params = dict(self.detail_endpoint.default_params)
        params["jobUnionId"] = post_id
        return params

    def parse_detail_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        status = payload.get("status")
        if status == 401:
            raise AuthError("美团详情接口返回 401 未授权")

        if status not in (0, 1):
            raise RuntimeError(f"美团详情接口返回异常: status={status}")
        data = payload.get("data")
        if not data:
            raise RuntimeError("美团详情接口未返回数据")
        return data

    def build_job_record(self, category_id: str, detail: Dict[str, Any], *, crawled_at: datetime) -> JobRecord:
        job_union_id = detail.get("jobUnionId", "")
        # 直接使用预期的字段进行提取
        title = detail.get("name", "")
        description = detail.get("jobDuty", "")
        requirement = detail.get("jobRequirement", "")
        bonus = detail.get("precedence", "")

        # 处理城市列表
        city_list = detail.get("cityList", [])
        if isinstance(city_list, list):
            location = " / ".join([str(city.get("name", "")) for city in city_list if isinstance(city, dict) and "name" in city])
        else:
            location = str(city_list)

        work_experience = detail.get("workYear", "")
        publish_time_raw = detail.get("refreshTime")
        publish_time = None
        # 处理时间戳，美团的时间戳可能是毫秒级
        if publish_time_raw:
            try:
                numeric_time = float(publish_time_raw)
                if numeric_time > 10**12:
                    numeric_time /= 1000
                # 注意：datetime.utcnow() 已弃用，使用 datetime.now(timezone.utc) (或为了兼容现架构先维持 UTC 原意)
                # python 3.12+ 推荐
                try:
                    from datetime import timezone
                    publish_time = datetime.fromtimestamp(numeric_time, tz=timezone.utc).replace(tzinfo=None)
                except ImportError:
                    pass
            except Exception:
                pass

        highlight_type = "campus" if self.job_type == 1 else "social"
        job_url = f"https://zhaopin.meituan.com/web/position/detail?jobUnionId={job_union_id}&highlightType={highlight_type}"

        return JobRecord(
            id=None,
            company_id=self.company_id,
            category_id=category_id,
            job_url=job_url,
            title=title,
            salary="面议",
            job_type=0,
            education=None,  # 根据需要可增加教育程度解析
            publish_time=publish_time,
            location=location,
            description=description,
            requirement=requirement,
            bonus=bonus,
            work_experience=work_experience,
            is_deleted=0,
            crawl_status=1,
            crawled_at=crawled_at,
            created_at=None,
        )

    def supports_auto_category(self) -> bool:
        return True

    def resolve_category_id(self, post: Dict[str, Any], detail: Dict[str, Any]) -> Optional[str]:
        # 从 post 或 detail 中获取分类的依据字段
        job_family = post.get("jobFamily") or detail.get("jobFamily")
        job_family_group = post.get("jobFamilyGroup") or detail.get("jobFamilyGroup")

        if not self._category_rules:
            return None

        for rule in self._category_rules:
            match = rule.get("match", {})
            if match.get("jobFamily") == job_family and match.get("jobFamilyGroup") == job_family_group:
                return rule.get("category_id")

        return None
