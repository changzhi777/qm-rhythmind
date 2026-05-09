# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 许可：CC BY-NC 4.0（非商业使用）/ 商业授权请联系作者
# ─────────────────────────────────────────────────────────────────────────────
"""
_version.py — 项目版本号单一来源（Single Source of Truth）

版本号由 scripts/bump_version.py 自动维护，
git pre-commit 钩子在每次提交时自动将第 3 位（patch）+1。

不要手动修改本文件，使用以下命令修改版本：
  python scripts/bump_version.py patch   # 0.1.1 → 0.1.2（默认，每次 commit 自动执行）
  python scripts/bump_version.py minor   # 0.1.1 → 0.2.0（新功能发布）
  python scripts/bump_version.py major   # 0.1.1 → 1.0.0（重大版本）
"""

__version__ = "0.1.5"
__version_info__ = tuple(int(x) for x in __version__.split("."))

# 版本元信息
__author__ = "外星动物（常智）/ IoTchange"
__email__ = "14455975@qq.com"
__license__ = "CC BY-NC 4.0"
__copyright__ = "Copyright 2024-2025 外星动物（常智）/ IoTchange"
