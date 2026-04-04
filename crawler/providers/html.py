from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from crawler.models import JobRecord
from crawler.providers.base import BaseProvider, ListResult, AuthError


class HtmlProvider(BaseProvider):
    """基于 HTML/XPath/CSS 解析的网页爬虫基类。

    适用于不返回结构化 JSON，而是直接返回 HTML 的传统招聘官网。
    子类需要实现 parse_list_html 和 parse_detail_html 方法，
    可以使用 BeautifulSoup、lxml 或正则表达式进行解析。
    """

    def fetch_posts(self, category_id: str, page: int) -> ListResult:
        """重写列表抓取逻辑：使用 fetch_text 获取 HTML 文本。"""
        payload = self.build_list_params(category_id, page)
        try:
            html = self.http_client.fetch_text(
                self.list_endpoint,
                payload,
                headers=self.list_headers(),
            )
            return self.parse_list_html(html, page, category_id)
        except AuthError:
            if self.refresh_auth():
                html = self.http_client.fetch_text(
                    self.list_endpoint,
                    payload,
                    headers=self.list_headers(),
                )
                return self.parse_list_html(html, page, category_id)
            else:
                raise

    def fetch_detail(self, post_id: str) -> Dict[str, Any]:
        """重写详情抓取逻辑：使用 fetch_text 获取 HTML 文本。"""
        payload = self.build_detail_params(post_id)
        try:
            html = self.http_client.fetch_text(
                self.detail_endpoint,
                payload,
                headers=self.detail_headers(),
            )
            return self.parse_detail_html(html, post_id)
        except AuthError:
            if self.refresh_auth():
                html = self.http_client.fetch_text(
                    self.detail_endpoint,
                    payload,
                    headers=self.detail_headers(),
                )
                return self.parse_detail_html(html, post_id)
            else:
                raise

    # ---- 留给子类实现的抽象方法 ----

    def parse_list_html(self, html: str, page: int, category_id: str) -> ListResult:
        """解析列表 HTML 并返回标准 ListResult，子类必须实现。"""
        raise NotImplementedError("HtmlProvider 子类必须实现 parse_list_html 方法")

    def parse_detail_html(self, html: str, post_id: str) -> Dict[str, Any]:
        """解析详情 HTML 并返回一个提取好字段的字典，供 build_job_record 使用，子类必须实现。"""
        raise NotImplementedError("HtmlProvider 子类必须实现 parse_detail_html 方法")

    def extract_post_id(self, post: Dict[str, Any]) -> Optional[str]:
        """对于 HTML 爬虫，post 通常是 parse_list_html 返回的一个个字典，这里需要提取唯一标识。"""
        raise NotImplementedError("HtmlProvider 子类必须实现 extract_post_id 方法")

    def build_job_record(self, category_id: str, detail: Dict[str, Any], *, crawled_at: datetime) -> JobRecord:
        """对于 HTML 爬虫，将提取出的 detail 字典转换为 JobRecord，子类必须实现。"""
        raise NotImplementedError("HtmlProvider 子类必须实现 build_job_record 方法")
