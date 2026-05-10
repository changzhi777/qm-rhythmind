# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Production Dockerfile
# ─────────────────────────────────────────────────────────────────────────────
# 设计要点：
#   - 多阶段构建：builder 安装依赖 → runtime 体积更小
#   - 非 root 用户运行（uid 1001）
#   - 默认 ENTRYPOINT 跑 Alembic upgrade head 再启动 uvicorn
#   - 内置 HEALTHCHECK 指向 /livez
#   - 强制要求 poetry.lock 存在；缺失即 fail-fast，避免不可重复构建
#   - Apple-only 依赖（mlx_lm 等）不在容器中安装；生产推理走 Ollama / LiteLLM
#
# 构建：
#   docker build -t rhythmind:0.1.5 .
#
# 运行（最小示例，生产请通过 Secret 注入 env）：
#   docker run --rm -p 8000:8000 \
#     -e ENV=prod \
#     -e JWT_SECRET=$(openssl rand -hex 32) \
#     -e DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/rhythmind \
#     -e MODEL_PRIMARY_SPEC=ollama://qwen2.5:7b \
#     -e RUN_MIGRATIONS_ON_STARTUP=true \
#     rhythmind:0.1.5
# ─────────────────────────────────────────────────────────────────────────────

# ── builder ──────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==${POETRY_VERSION}"

# 依赖安装：lock 文件必须存在以保证可重复构建。
# 仓库当前缺 poetry.lock —— CI 第一次跑 `poetry lock --no-update` 即可生成。
COPY pyproject.toml poetry.lock ./
RUN poetry install --without cv,dev --no-root \
    && rm -rf $POETRY_CACHE_DIR

# 拷贝源码并安装本包（不再装一次 deps，加速构建）
COPY src/ ./src/
COPY data/ ./data/
COPY alembic.ini ./
RUN poetry install --without cv,dev --only-root

# ── runtime ──────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8000 \
    UVICORN_WORKERS=2

# 构建时注入：CI 在 docker build 时传递 --build-arg GIT_SHA=$(git rev-parse HEAD) 等
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
ENV RHYTHMIND_GIT_SHA=$GIT_SHA \
    RHYTHMIND_BUILD_TIME=$BUILD_TIME

WORKDIR /app

# runtime 只装运行期所需 system lib（libpq 用于 asyncpg 二进制依赖；curl 用于 healthcheck）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 rhythmind \
    && useradd  --system --uid 1001 --gid rhythmind --home /app rhythmind

# 从 builder 阶段拷贝虚拟环境与源码
COPY --from=builder --chown=rhythmind:rhythmind /app/.venv     /app/.venv
COPY --from=builder --chown=rhythmind:rhythmind /app/src       /app/src
COPY --from=builder --chown=rhythmind:rhythmind /app/data      /app/data
COPY --from=builder --chown=rhythmind:rhythmind /app/alembic.ini /app/alembic.ini

# Entrypoint：可选迁移 → 启动 uvicorn
COPY --chown=rhythmind:rhythmind scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER rhythmind

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:${PORT}/livez || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "rhythmind.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
