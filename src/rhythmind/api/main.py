# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
api/main.py — FastAPI 应用入口

启动顺序：
  lifespan → init_db() → 路由挂载 → uvicorn

本地开发：
  uvicorn rhythmind.api.main:app --reload --port 8000

生产：
  gunicorn rhythmind.api.main:app -w 4 -k uvicorn.workers.UvicornWorker
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from rhythmind.config import settings
from rhythmind.core.memory import init_db

# 路由
from rhythmind.api.routers.health import router as health_router
from rhythmind.mcp.router import router as mcp_router

log = structlog.get_logger(__name__)


# ── structlog 基础配置 ────────────────────────────────────────────────────

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if settings.env == "dev"
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.DEBUG if settings.debug else logging.INFO
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)


# ── lifespan（应用生命周期）──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    启动：初始化数据库表 + AgentPool 后台清理任务
    关闭：取消清理任务 + 释放连接池
    """
    import asyncio
    log.info("rhythmind.startup env=%s debug=%s", settings.env, settings.debug)

    # 初始化 SQLAlchemy 表（开发用；生产走 Alembic migration）
    await init_db()
    log.info("rhythmind.db_ready")

    # AgentPool 后台清理任务（每 5 分钟清理过期 Agent）
    from rhythmind.api.deps import get_pool
    pool = get_pool()

    async def _pool_cleanup() -> None:
        while True:
            await asyncio.sleep(300)
            try:
                purged = await pool.purge_expired()
                if purged:
                    log.info("pool.cleanup purged=%d", purged)
            except Exception as exc:
                log.warning("pool.cleanup error=%s", exc)

    cleanup_task = asyncio.create_task(_pool_cleanup())
    log.info("rhythmind.pool_cleanup_task started pool_max=%d", pool.max_users)

    yield  # 应用运行期间

    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    # 关闭时清理
    from rhythmind.api.deps import _router_instance
    if _router_instance:
        await _router_instance.close()
    log.info("rhythmind.shutdown complete")


# ── FastAPI 实例 ──────────────────────────────────────────────────────────

app = FastAPI(
    title="律动 RHYTHMIND API",
    description="Multi-agent AI Health Platform — AG2 + Hermes Architecture",
    version="0.1.0",
    docs_url="/docs" if settings.env != "prod" else None,
    redoc_url="/redoc" if settings.env != "prod" else None,
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.env == "dev" else ["https://app.rhythmind.ai"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 全局异常处理 ──────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_exception path=%s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "内部服务错误，请稍后重试。"},
    )


# ── 路由挂载 ──────────────────────────────────────────────────────────────

app.include_router(health_router, prefix="/api/v1")
app.include_router(mcp_router)  # /mcp/sse  +  /mcp/messages/


# ── 健康检查 ──────────────────────────────────────────────────────────────

@app.get("/ping", tags=["infra"])
async def ping() -> dict[str, str]:
    return {"status": "ok", "env": settings.env}


@app.get("/health", tags=["infra"])
async def health_check() -> dict[str, str]:
    """负载均衡器健康探针。"""
    return {"status": "healthy", "version": "0.1.0"}
