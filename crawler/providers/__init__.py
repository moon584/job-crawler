"""Provider registry，用于按官网类型选择不同的字段解析逻辑。"""

from __future__ import annotations

from typing import Dict, Type

from crawler.rules import CompanyRule

from .base import BaseProvider
from .config_provider import ConfigDrivenProvider

_PROVIDER_REGISTRY: Dict[str, Type[BaseProvider]] = {
    "config": ConfigDrivenProvider,
    "tencent": ConfigDrivenProvider,
}


def load_provider(name: str, rule: CompanyRule, http_client=None) -> BaseProvider:
    key = name.lower().strip()

    # 动态加载具体的定制 Provider
    if key == "meituan":
        try:
            from .impl.meituan import MeituanProvider
            _PROVIDER_REGISTRY[key] = MeituanProvider
        except ImportError:
            raise ImportError("无法加载 meituan provider，请确保 providers/impl/meituan.py 存在")

    if key not in _PROVIDER_REGISTRY:
        available = ", ".join(sorted(_PROVIDER_REGISTRY.keys()))
        raise ValueError(f"未知 provider '{name}'，可选值：{available}")
    provider_cls = _PROVIDER_REGISTRY[key]
    return provider_cls(rule, http_client=http_client)
