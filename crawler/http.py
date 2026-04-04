from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, Optional

import requests

from .rules import APIEndpoint, ThrottleRule


class HttpClient:
    """带节流/重试的简单HTTP客户端（中文注释）。"""

    def __init__(self, throttle: ThrottleRule) -> None:
        self._throttle = throttle
        self._session = requests.Session()

    def fetch_json(self, endpoint: APIEndpoint, extra_params: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """按规则发起HTTP请求并返回JSON（中文注释）。"""
        params = dict(endpoint.default_params)
        params.update(extra_params)
        return self._request(endpoint, params, headers, return_json=True)

    def fetch_text(self, endpoint: APIEndpoint, extra_params: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> str:
        """按规则发起HTTP请求并返回原始文本（中文注释）。"""
        params = dict(endpoint.default_params)
        params.update(extra_params)
        return self._request(endpoint, params, headers, return_json=False)

    def warmup(self, url: str, headers: Optional[Dict[str, str]] = None) -> None:
        """预热会话：访问页面以获取服务端下发的会话cookie。"""
        backoff = 1.0
        last_error: Optional[Exception] = None
        request_headers = self._sanitize_headers(headers)
        for attempt in range(1, self._throttle.max_retries + 1):
            self._sleep_once()
            try:
                response = self._session.get(
                    url,
                    headers=request_headers or None,
                    timeout=self._throttle.timeout,
                )
                response.raise_for_status()
                return
            except requests.RequestException as exc:
                last_error = exc
                logging.warning(
                    "Warmup request failed (attempt %s/%s): %s",
                    attempt,
                    self._throttle.max_retries,
                    exc,
                )
            if attempt == self._throttle.max_retries:
                break
            time.sleep(backoff)
            backoff *= self._throttle.retry_backoff
        if last_error:
            raise last_error

    def _request(self, endpoint: APIEndpoint, payload: Dict[str, Any], headers: Optional[Dict[str, str]], return_json: bool = True) -> Any:
        """包含指数退避重试的底层请求逻辑（中文注释）。"""
        backoff = 1.0
        last_error: Optional[Exception] = None
        method = (endpoint.method or "GET").upper()
        if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
            raise ValueError(f"Unsupported HTTP method: {method}")
        request_fn = getattr(self._session, "request", None)
        legacy_get = getattr(self._session, "get", None)
        if request_fn is None and method != "GET":
            raise ValueError("Current HTTP session does not support non-GET methods; please supply a requests.Session with request().")
        for attempt in range(1, self._throttle.max_retries + 1):
            self._sleep_once()
            response: Optional[requests.Response] = None
            request_headers = self._sanitize_headers(headers)
            if method != "GET" and not any(key.lower() == "content-type" for key in request_headers):
                request_headers["Content-Type"] = "application/json"
            try:
                if request_fn is not None:
                    response = request_fn(
                        method,
                        endpoint.url,
                        params=payload if method == "GET" else None,
                        json=None if method == "GET" else payload,
                        headers=request_headers or None,
                        timeout=self._throttle.timeout,
                    )
                else:
                    response = legacy_get(
                        endpoint.url,
                        params=payload,
                        headers=request_headers or None,
                        timeout=self._throttle.timeout,
                    )
                response.raise_for_status()
                if return_json:
                    return response.json()
                else:
                    return response.text
            except requests.RequestException as exc:
                last_error = exc
                logging.warning(
                    "HTTP request failed (attempt %s/%s): %s",
                    attempt,
                    self._throttle.max_retries,
                    exc,
                )
            except ValueError as exc:
                status = response.status_code if response is not None else "-"
                preview = (response.text or "")[:200] if response is not None else ""
                error = RuntimeError(
                    "Failed to parse JSON from %s (status=%s): %s"
                    % (endpoint.url, status, preview.replace("\n", " "))
                )
                last_error = error
                logging.warning(
                    "HTTP JSON decode failed (attempt %s/%s, status=%s): %s",
                    attempt,
                    self._throttle.max_retries,
                    status,
                    preview.strip(),
                )
            if attempt == self._throttle.max_retries:
                if last_error:
                    raise last_error
                raise RuntimeError("Retry loop exhausted without raising")
            time.sleep(backoff)
            backoff *= self._throttle.retry_backoff
        if last_error:
            raise last_error
        raise RuntimeError("Retry loop exhausted without raising")

    @staticmethod
    def _sanitize_headers(headers: Optional[Dict[str, str]]) -> Dict[str, str]:
        cleaned: Dict[str, str] = {}
        for key, value in (headers or {}).items():
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            cleaned[key] = text
        return cleaned

    def _sleep_once(self) -> None:
        """根据 throttle 范围随机延迟，降低压力（中文注释）。"""
        delay = random.uniform(self._throttle.min_seconds, self._throttle.max_seconds)
        time.sleep(delay)

    def close(self) -> None:
        """关闭底层Session（中文注释）。"""
        self._session.close()

