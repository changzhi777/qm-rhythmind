#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 容器入口脚本
# ─────────────────────────────────────────────────────────────────────────────
# 行为：
#   1. 若 RUN_MIGRATIONS_ON_STARTUP=true，先跑 alembic upgrade head（失败即退出）
#   2. 若 ENV=prod 且 JWT_SECRET 长度 < 32，立刻退出（防默认密钥上线）
#   3. exec "$@" 切换到 CMD 指定的进程，使其成为 PID 1（接收 SIGTERM）
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

log() { printf '[entrypoint] %s\n' "$*" >&2; }

# ── 生产环境冗余防御（config.py 也会在 lifespan 内做完整断言）───────────────
if [[ "${ENV:-dev}" == "prod" ]]; then
    if [[ -z "${JWT_SECRET:-}" || "${#JWT_SECRET}" -lt 32 ]]; then
        log "FATAL: ENV=prod requires JWT_SECRET with >=32 chars"
        exit 1
    fi
    if [[ "${LITELLM_MASTER_KEY:-sk-1234}" == "sk-1234" || "${LITELLM_MASTER_KEY:-}" == "sk-test" ]]; then
        log "FATAL: ENV=prod with default LITELLM_MASTER_KEY"
        exit 1
    fi
fi

# ── Alembic 迁移（容器化推荐做法）───────────────────────────────────────────
if [[ "${RUN_MIGRATIONS_ON_STARTUP:-false}" == "true" ]]; then
    log "running alembic upgrade head ..."
    alembic upgrade head
    log "alembic upgrade complete"
fi

log "starting: $*"
exec "$@"
