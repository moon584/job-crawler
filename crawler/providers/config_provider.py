from __future__ import annotations

import os
from datetime import datetime
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from crawler.models import JobRecord
from crawler.utils import parse_publish_time

from .base import BaseProvider, ListResult

_TEXT_FIELDS = {
    "job_url",
    "title",
    "salary",
    "location",
    "description",
    "requirement",
    "bonus",
    "work_experience",
    "education",
}

REQUIRED_FIELDS = (
    "job_url",
)


@dataclass(slots=True)
class ResponseConfig:
    code_field: str = "Code"
    success_value: int = 200
    data_path: Optional[str] = "Data"
    posts_path: Optional[str] = "Posts"
    count_path: Optional[str] = "Count"
    post_id_field: str = "PostId"
    page_param: str = "pageIndex"
    size_param: str = "pageSize"
    page_size: Optional[int] = None
    timestamp_param: Optional[str] = None
    category_param: Optional[str] = "categoryId"


class ConfigDrivenProvider(BaseProvider):
    """通用配置驱动 Provider，通过 JSON 描述官网差异。"""

    def __init__(self, rule) -> None:  # type: ignore[override]
        super().__init__(rule)
        self.extra = self._expand_env_vars(deepcopy(self.extra))
        list_cfg = self.extra.get("list", {})
        detail_cfg = self.extra.get("detail", {})
        self._list_headers = self.extra.get("list_headers") or self.extra.get("headers")
        self._detail_headers = self.extra.get("detail_headers") or self.extra.get("headers")
        self.url_templates: Dict[str, str] = self.extra.get("url_templates", {})
        self.list_config = ResponseConfig(
            code_field=list_cfg.get("code_field", "Code"),
            success_value=list_cfg.get("success_value", 200),
            data_path=list_cfg.get("data_path", "Data"),
            posts_path=list_cfg.get("posts_path", "Posts"),
            count_path=list_cfg.get("count_path", "Count"),
            post_id_field=list_cfg.get("post_id_field", "PostId"),
            page_param=list_cfg.get("page_param", "pageIndex"),
            size_param=list_cfg.get("size_param", "pageSize"),
            page_size=list_cfg.get("page_size"),
            timestamp_param=list_cfg.get("timestamp_param", "timestamp"),
            category_param=list_cfg.get("category_param", "categoryId"),
        )
        self.detail_config = ResponseConfig(
            code_field=detail_cfg.get("code_field", "Code"),
            success_value=detail_cfg.get("success_value", 200),
            data_path=detail_cfg.get("data_path", "Data"),
            timestamp_param=detail_cfg.get("timestamp_param", "timestamp"),
        )
        self.field_map: Dict[str, str] = self.extra.get("field_map", {})
        self.default_values: Dict[str, Any] = self.extra.get("default_values", {})
        self._validate_required_fields()

    # ---- 列表阶段 ----
    def list_headers(self) -> Optional[Dict[str, str]]:  # type: ignore[override]
        return self._list_headers

    def build_list_params(self, category_id: str, page: int) -> Dict[str, Any]:  # type: ignore[override]
        params = super().build_list_params(category_id, page)
        params[self.list_config.page_param] = page
        if self.list_config.size_param and self.list_config.size_param not in params and self.list_config.page_size:
            params[self.list_config.size_param] = self.list_config.page_size
        if self.list_config.category_param and category_id:
            params[self.list_config.category_param] = category_id
        if self.list_config.timestamp_param:
            params[self.list_config.timestamp_param] = self._current_timestamp()
        return params

    def parse_list_response(self, payload: Dict[str, Any], page: int) -> ListResult:  # type: ignore[override]
        code = self._resolve_path(payload, self.list_config.code_field)
        if code != self.list_config.success_value:
            raise RuntimeError(f"列表接口返回异常 Code={code}")
        data = self._resolve_path(payload, self.list_config.data_path) or {}
        posts: List[Dict[str, Any]] = self._resolve_path(data, self.list_config.posts_path) or []
        total_count_raw = self._resolve_path(data, self.list_config.count_path)
        total_count = int(total_count_raw) if total_count_raw is not None else None
        page_size = self.list_config.page_size or self._infer_page_size()
        has_more = bool(posts) and (
            (total_count is not None and page * page_size < total_count)
            or (total_count is None and len(posts) == page_size)
        )
        return ListResult(posts=posts, total_count=total_count, has_more=has_more)

    def extract_post_id(self, post: Dict[str, Any]) -> Optional[str]:  # type: ignore[override]
        value = self._resolve_path(post, self.list_config.post_id_field)
        return str(value).strip() if value else None

    # ---- 详情阶段 ----
    def build_detail_params(self, post_id: str) -> Dict[str, Any]:  # type: ignore[override]
        params = dict(self.detail_endpoint.default_params)
        post_id_key = self.detail_config.post_id_field or "postId"
        params[post_id_key] = post_id
        if post_id_key != "postId":
            params.pop("postId", None)
        if self.detail_config.timestamp_param:
            params[self.detail_config.timestamp_param] = self._current_timestamp()
        return params

    def detail_headers(self) -> Optional[Dict[str, str]]:  # type: ignore[override]
        return self._detail_headers

    def parse_detail_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[override]
        code = self._resolve_path(payload, self.detail_config.code_field)
        if code != self.detail_config.success_value:
            raise RuntimeError(f"详情接口返回异常 Code={code}")
        data = self._resolve_path(payload, self.detail_config.data_path)
        if not data:
            raise RuntimeError("详情接口未返回数据")
        return data

    # ---- 映射阶段 ----
    def build_job_record(self, category_id: str, detail: Dict[str, Any], *, crawled_at: datetime) -> JobRecord:  # type: ignore[override]
        record = JobRecord(
            id=None,
            company_id=self.company_id,
            category_id=category_id,
            job_url=self._string_field(detail, "job_url"),
            title=self._string_field(detail, "title"),
            salary=self._string_field(detail, "salary") or self.default_values.get("salary", "面议"),
            job_type=0,
            education=self._string_field(detail, "education"),
            publish_time=self._publish_time_field(detail),
            location=self._string_field(detail, "location"),
            description=self._string_field(detail, "description") or "",
            requirement=self._string_field(detail, "requirement"),
            bonus=self._string_field(detail, "bonus") or self.default_values.get("bonus"),
            work_experience=self._string_field(detail, "work_experience"),
            crawl_status=1,
            crawled_at=crawled_at,
            created_at=None,
        )
        return self._apply_templates(record, detail)

    # ---- 工具方法 ----
    @staticmethod
    def _current_timestamp() -> int:
        return int(datetime.utcnow().timestamp() * 1000)

    def _resolve_path(self, payload: Optional[Dict[str, Any]], path: Optional[str]) -> Any:
        if payload is None or not path:
            return payload
        parts = [p for p in path.split(".") if p]
        current: Any = payload
        for key in parts:
            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, list):
                try:
                    index = int(key)
                except ValueError:
                    return None
                if index < 0 or index >= len(current):
                    return None
                current = current[index]
            else:
                return None
        return current

    def _string_field(self, detail: Dict[str, Any], field_name: str) -> Optional[str]:
        path = self.field_map.get(field_name)
        if not path:
            value = self.default_values.get(field_name)
        else:
            value = self._resolve_path(detail, path)
        if value is None:
            return None
        if field_name in _TEXT_FIELDS:
            return str(value).strip()
        return value

    def _publish_time_field(self, detail: Dict[str, Any]) -> Optional[datetime]:
        raw_path = self.field_map.get("publish_time")
        raw_value = self._resolve_path(detail, raw_path) if raw_path else None
        numeric_time = self._parse_epoch_time(raw_value)
        if numeric_time is not None:
            return numeric_time
        if raw_value is None:
            fallback = self.default_values.get("publish_time")
            return parse_publish_time(fallback) if fallback else None
        return parse_publish_time(str(raw_value))

    @staticmethod
    def _parse_epoch_time(value: Any) -> Optional[datetime]:
        if isinstance(value, (int, float)):
            numeric = float(value)
        elif isinstance(value, str) and value.isdigit():
            numeric = float(int(value))
        else:
            return None
        if numeric > 10**12:
            numeric /= 1000
        if numeric <= 0:
            return None
        return datetime.utcfromtimestamp(numeric)

    def _apply_templates(self, record: JobRecord, detail: Dict[str, Any]) -> JobRecord:
        if not self.url_templates:
            return record
        job_url_template = self.url_templates.get("job_url")
        if job_url_template:
            rendered = self._render_template(job_url_template, detail)
            if rendered:
                record.job_url = rendered
        return record

    @staticmethod
    def _render_template(template: str, context: Dict[str, Any]) -> Optional[str]:
        class _SafeDict(dict):
            def __missing__(self, key: str) -> str:  # type: ignore[override]
                return ""

        try:
            return template.format_map(_SafeDict(context))
        except Exception:
            return None

    def _validate_required_fields(self) -> None:
        missing: List[str] = []
        for field in REQUIRED_FIELDS:
            path = self.field_map.get(field)
            default = self.default_values.get(field)
            if not path and default in (None, ""):
                missing.append(field)
        if missing:
            raise ValueError(
                f"公司 {self.company_id} 的配置缺少必填字段映射: {', '.join(missing)}"
            )

    def _expand_env_vars(self, value: Any) -> Any:
        if isinstance(value, str):
            return os.path.expandvars(value)
        if isinstance(value, dict):
            return {k: self._expand_env_vars(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._expand_env_vars(item) for item in value]
        return value

