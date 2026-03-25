from __future__ import annotations

from datetime import datetime
from typing import Optional


SUPPORTED_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y年%m月%d日",
)


def parse_publish_time(raw_value: Optional[str]) -> Optional[datetime]:
    """解析多种官网时间格式（中文注释）。"""
    if not raw_value:
        return None
    sanitized = raw_value.strip()
    for pattern in SUPPORTED_TIME_FORMATS:
        try:
            parsed = datetime.strptime(sanitized, pattern)
            if "H" not in pattern:
                return parsed.replace(hour=0, minute=0, second=0)
            return parsed
        except ValueError:
            continue
    return None


def normalize_category_id(raw_value: str) -> str:
    """兼容不同官网的分类ID，允许非 8 位数字，必要时补 0。"""
    if raw_value is None:
        raise ValueError("categoryid 不能为空")
    text = str(raw_value).strip()
    if not text:
        raise ValueError("categoryid 不能为空字符串")
    digits_only = text.isdigit()
    if digits_only and len(text) == 7:
        text = f"{text[:3]}0{text[3:]}"
    if digits_only:
        return text
    return text.upper()
