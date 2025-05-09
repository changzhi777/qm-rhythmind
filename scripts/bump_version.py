#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — 版本号自动升级脚本
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 许可：CC BY-NC 4.0（非商业使用）/ 商业授权请联系作者
# ─────────────────────────────────────────────────────────────────────────────
"""
scripts/bump_version.py — 版本号自动升级

用法：
  python scripts/bump_version.py          # 默认 patch（第3位+1）
  python scripts/bump_version.py patch    # 0.1.1 → 0.1.2
  python scripts/bump_version.py minor    # 0.1.1 → 0.2.0
  python scripts/bump_version.py major    # 0.1.1 → 1.0.0

由 .githooks/pre-commit 自动调用（每次 git commit 时触发）。
同步更新以下文件：
  - VERSION
  - src/rhythmind/_version.py
  - pyproject.toml（version 字段）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def read_version() -> str:
    return (ROOT / "VERSION").read_text().strip()


def write_version(new_ver: str) -> None:
    # 1. VERSION 文件
    (ROOT / "VERSION").write_text(f"{new_ver}\n")

    # 2. src/rhythmind/_version.py
    ver_path = ROOT / "src" / "rhythmind" / "_version.py"
    content = ver_path.read_text()
    content = re.sub(
        r'__version__\s*=\s*"[\d.]+"',
        f'__version__ = "{new_ver}"',
        content,
    )
    ver_path.write_text(content)

    # 3. pyproject.toml
    toml_path = ROOT / "pyproject.toml"
    content = toml_path.read_text()
    content = re.sub(
        r'^(version\s*=\s*)"[\d.]+"',
        f'\\g<1>"{new_ver}"',
        content,
        flags=re.MULTILINE,
    )
    toml_path.write_text(content)


def bump(part: str = "patch") -> str:
    current = read_version()
    major, minor, patch = (int(x) for x in current.split("."))

    if part == "major":
        major += 1
        minor = 0
        patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    else:  # patch（默认）
        patch += 1

    new_ver = f"{major}.{minor}.{patch}"
    write_version(new_ver)
    print(f"  版本升级：{current} → {new_ver}  ({part})")
    return new_ver


if __name__ == "__main__":
    part = sys.argv[1] if len(sys.argv) > 1 else "patch"
    if part not in ("major", "minor", "patch"):
        print(f"错误：未知的版本部分 '{part}'，请使用 major / minor / patch")
        sys.exit(1)
    bump(part)
