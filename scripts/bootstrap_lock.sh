#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# scripts/bootstrap_lock.sh — 生成 poetry.lock（首次或依赖变更后）
# ─────────────────────────────────────────────────────────────────────────────
# 何时运行:
#   - 首次 clone 仓库准备构建 Docker 镜像时
#   - pyproject.toml 中的依赖发生增删改时（CI 也会自动校验）
#
# 前置: 系统已装 Python 3.12 + Poetry 1.8.x
#   brew install python@3.12 poetry        # macOS
#   apt install python3.12 && pipx install poetry==1.8.3   # Ubuntu
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

if ! command -v poetry >/dev/null; then
    echo "FATAL: poetry not found. See header comment for install instructions." >&2
    exit 1
fi

# Apple Silicon 上 mlx_lm 等 platform-specific 依赖会跑全；其他平台跳过 cv 组。
ARGS=()
if [[ "${SKIP_CV:-1}" == "1" ]]; then
    ARGS+=(--without cv)
fi

echo "[bootstrap_lock] poetry lock --no-update ${ARGS[*]:-}"
poetry lock --no-update

echo "[bootstrap_lock] done. commit poetry.lock to lock dependency tree."
