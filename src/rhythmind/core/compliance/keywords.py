# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
core/compliance/keywords.py — 关键词加载器

从 data/compliance_rules/medical_keywords.yaml 加载规则，
编译正则，缓存到模块级变量（应用启动时加载一次）。
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

import yaml  # type: ignore[import-untyped]


class KeywordRules(NamedTuple):
    block_patterns: list[re.Pattern[str]]
    warn_patterns: list[re.Pattern[str]]
    disclaimer_zh: str


def _compile_patterns(raw: list[str]) -> list[re.Pattern[str]]:
    patterns = []
    for item in raw:
        if item.startswith("regex:"):
            pattern = item[len("regex:"):].strip()
        else:
            pattern = re.escape(item)
        patterns.append(re.compile(pattern, re.UNICODE))
    return patterns


@lru_cache(maxsize=1)
def load_keyword_rules(
    rules_path: str | None = None,
) -> KeywordRules:
    if rules_path is None:
        # 相对项目根目录定位
        base = Path(__file__).resolve().parents[4]  # src/rhythmind/core/compliance/ → root  # noqa: E501
        rules_path = str(base / "data" / "compliance_rules" / "medical_keywords.yaml")

    with open(rules_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return KeywordRules(
        block_patterns=_compile_patterns(data.get("block_keywords", [])),
        warn_patterns=_compile_patterns(data.get("warn_keywords", [])),
        disclaimer_zh=data.get("disclaimer_zh", "").strip(),
    )
