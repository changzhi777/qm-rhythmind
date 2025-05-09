#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND — Git 钩子安装脚本
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────
#
# 用法（克隆仓库后执行一次）：
#   chmod +x setup_hooks.sh && ./setup_hooks.sh
#
# 效果：
#   将 .githooks/ 目录设为 Git 钩子目录，
#   pre-commit 钩子在每次 commit 时自动将版本 patch+1。
#

set -e

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
HOOKS_DIR="$REPO_ROOT/.githooks"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  RHYTHMIND Git 钩子安装"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 设置 hooksPath（Git 2.9+）
git config core.hooksPath "$HOOKS_DIR"

# 确保钩子可执行
chmod +x "$HOOKS_DIR"/pre-commit 2>/dev/null || true

echo "✅ Git 钩子目录已设置为：$HOOKS_DIR"
echo "✅ pre-commit 钩子：每次 commit 自动升级 patch 版本"
echo ""
echo "提示：跳过版本升级用 git commit --no-verify"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
