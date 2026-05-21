# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
api/main.py — FastAPI 应用入口

启动顺序：
  lifespan → assert_production_safe() → [optional alembic upgrade head]
            → init_db() → 路由挂载 → uvicorn

本地开发：
  uvicorn rhythmind.api.main:app --reload --port 8000

生产：
  gunicorn rhythmind.api.main:app -w 4 -k uvicorn.workers.UvicornWorker
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from rhythmind import __version__ as RHYTHMIND_VERSION

# 路由
from rhythmind.api.routers.admin import router as admin_router
from rhythmind.api.routers.dashboard import router as dashboard_router
from rhythmind.api.routers.health import router as health_router
from rhythmind.api.routers.medical import router as medical_router
from rhythmind.api.routers.privacy import router as privacy_router
from rhythmind.config import settings
from rhythmind.core.memory import init_db
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
    启动：
      1. 生产配置安全断言（settings.assert_production_safe）
      2. （可选）Alembic upgrade head — 由 RUN_MIGRATIONS_ON_STARTUP 控制
      3. init_db() 兜底建表（开发用）
      4. Sentry 初始化（若配置 SENTRY_DSN）
      5. AgentPool 后台清理任务
    关闭：取消清理任务 + 释放连接池
    """
    import asyncio
    log.info(
        "rhythmind.startup env=%s debug=%s version=%s",
        settings.env, settings.debug, RHYTHMIND_VERSION,
    )

    # 1. 生产环境安全断言（不安全配置直接拒绝启动）
    try:
        settings.assert_production_safe()
    except RuntimeError as exc:
        try:
            from rhythmind.audit import AuditEvent, audit_log
            audit_log(
                AuditEvent.CONFIG_UNSAFE_STARTUP,
                env=settings.env,
                reason=str(exc),
            )
        except Exception:
            pass
        raise

    # 2. Alembic 自动迁移（容器化推荐）
    if settings.run_migrations_on_startup:
        try:
            from alembic import command
            from alembic.config import Config as AlembicConfig
            cfg = AlembicConfig("alembic.ini")
            await asyncio.to_thread(command.upgrade, cfg, "head")
            log.info("rhythmind.alembic_upgraded")
        except Exception as exc:
            log.error("rhythmind.alembic_failed error=%s", exc)
            raise

    # 3. SQLAlchemy 兜底建表（生产应通过 Alembic，这一步幂等）
    await init_db()
    log.info("rhythmind.db_ready")

    # 4. Sentry（仅在配置了 DSN 时启用）
    if settings.sentry_dsn:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            sentry_sdk.init(
                dsn=settings.sentry_dsn,
                environment=settings.env,
                release=RHYTHMIND_VERSION,
                integrations=[FastApiIntegration()],
                traces_sample_rate=0.1 if settings.env == "prod" else 1.0,
                send_default_pii=False,  # 健康数据合规：禁止默认上报 PII
            )
            log.info("rhythmind.sentry_initialized")
        except Exception as exc:
            log.warning("rhythmind.sentry_init_failed error=%s", exc)

    # 5. AgentPool 后台清理任务（每 5 分钟清理过期 Agent）
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
    with suppress(asyncio.CancelledError):
        await cleanup_task

    # 关闭时清理
    from rhythmind.api.deps import _router_instance
    if _router_instance:
        await _router_instance.close()
    log.info("rhythmind.shutdown complete")


# ── FastAPI 实例 ──────────────────────────────────────────────────────────

app = FastAPI(
    title="律动 RHYTHMIND API",
    description="Multi-agent AI Health Platform — AG2 + Hermes Architecture",
    version=RHYTHMIND_VERSION,
    docs_url="/docs" if settings.env != "prod" else None,
    redoc_url="/redoc" if settings.env != "prod" else None,
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────
# 安全规则：
#   1) 生产 origin 列表必须显式提供（CORS_ALLOW_ORIGINS env），空列表即拒绝所有跨域。
#   2) 永远不允许 "*" + allow_credentials=True（违反 CORS 规范）。
#   3) dev 默认放行 localhost:3000/5173，方便前端调试。

_origins = settings.cors_origins_list

if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
    )
    log.info("cors.configured origins=%s", _origins)
else:
    log.warning("cors.disabled no_origins_configured env=%s", settings.env)


# ── 请求体大小硬上限（早于业务路由）──────────────────────────────────────
from rhythmind.api.middleware import RequestSizeLimitMiddleware  # noqa: E402

app.add_middleware(RequestSizeLimitMiddleware)


# ── 可观测性：Prometheus + OTel ─────────────────────────────────────────────
# 调用顺序很关键：metrics 中间件应早于其他可能 swallow 异常的中间件，
# 这样无论后续 handler 如何，HTTP_REQUESTS 都能记录到。
from rhythmind.observability import install_metrics, install_tracing  # noqa: E402

install_metrics(app)
install_tracing(app, service_name="rhythmind-api")


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
app.include_router(medical_router, prefix="/api/v1")  # /medical/analyze, /timeline, /medications, /labs/{test}
app.include_router(privacy_router, prefix="/api/v1")  # /privacy/export, /delete, /policy
app.include_router(admin_router, prefix="/api/v1")    # /admin/skills/* (R-4)
app.include_router(dashboard_router)    # /api/dashboard, /api/reports, /api/analyze
app.include_router(mcp_router)  # /mcp/sse  +  /mcp/messages/


# ── 健康检查（K8s 探针分级）──────────────────────────────────────────────
#   /livez  : 进程存活（不依赖外部组件）— 用于 livenessProbe
#   /readyz : 是否可接流量（DB/Redis/QMD 检查）— 用于 readinessProbe
#   /health : 兼容旧负载均衡器，等价 /livez
#   /ping   : 兼容旧脚本

@app.get("/ping", tags=["infra"], include_in_schema=False)
async def ping() -> dict[str, str]:
    return {"status": "ok", "env": settings.env}


@app.get("/livez", tags=["infra"])
async def livez() -> dict[str, str]:
    """K8s livenessProbe — 进程能响应即视为存活。"""
    return {"status": "alive", "version": RHYTHMIND_VERSION}


@app.get("/readyz", tags=["infra"])
async def readyz() -> JSONResponse:
    """
    K8s readinessProbe — 检查关键依赖：DB / Redis。
    任何依赖不可达返回 503，让 K8s 把流量切走。
    """
    checks: dict[str, str] = {}
    overall_ok = True

    # DB
    try:
        from sqlalchemy import text

        from rhythmind.core.memory.manager import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"fail: {exc.__class__.__name__}"
        overall_ok = False

    # Redis（LoopGuard 依赖）
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        await r.ping()
        # aclose 在 redis>=5.0.1 取代 close；保留 fallback 兼容更老版本
        if hasattr(r, "aclose"):
            await r.aclose()
        else:
            await r.close()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"fail: {exc.__class__.__name__}"
        overall_ok = False

    # 可选：LLM 上游（LiteLLM + oMLX）
    # 默认关闭，避免每次 K8s 探针打第三方 API。
    if settings.readyz_check_llm_upstream:
        import asyncio as _aio

        async def _check_litellm() -> str:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=settings.readyz_llm_timeout) as cli:
                    resp = await cli.get(f"{settings.litellm_url}/health")
                    if resp.status_code < 500:
                        return "ok"
                    return f"fail: status={resp.status_code}"
            except Exception as exc:
                return f"fail: {exc.__class__.__name__}"

        async def _check_omlX() -> str:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=settings.readyz_llm_timeout) as cli:
                    resp = await cli.get(
                        f"{settings.omlX_base_url.rstrip('/')}/v1/models",
                        headers={"Authorization": f"Bearer {settings.omlX_api_key}"},
                    )
                    if resp.status_code < 500:
                        return "ok"
                    return f"fail: status={resp.status_code}"
            except Exception as exc:
                return f"fail: {exc.__class__.__name__}"

        litellm_status, omlX_status = await _aio.gather(_check_litellm(), _check_omlX())
        checks["litellm"] = litellm_status
        checks["omlX"]     = omlX_status
        if not litellm_status.startswith("ok") and not omlX_status.startswith("ok"):
            # 两者全挂才算 not_ready：单个挂掉时 adapter_router 内部会 fallback
            overall_ok = False

    body = {
        "status": "ready" if overall_ok else "not_ready",
        "version": RHYTHMIND_VERSION,
        "checks": checks,
    }
    return JSONResponse(status_code=200 if overall_ok else 503, content=body)


@app.get("/health", tags=["infra"], include_in_schema=False)
async def health_check() -> dict[str, str]:
    """兼容旧负载均衡器（=livez）。新接入请使用 /livez 或 /readyz。"""
    return {"status": "healthy", "version": RHYTHMIND_VERSION}


@app.get("/version", tags=["infra"])
async def version() -> dict[str, str]:
    """
    暴露当前实例的版本信息（运维定位"哪个 Pod 跑哪版本"）。

    git_sha / build_time 通过 Dockerfile 构建时注入的环境变量读取；
    本地启动时返回 "unknown"。

    生产构建建议在 Dockerfile 里：
      ARG GIT_SHA
      ARG BUILD_TIME
      ENV RHYTHMIND_GIT_SHA=$GIT_SHA RHYTHMIND_BUILD_TIME=$BUILD_TIME
    """
    import os
    return {
        "version":    RHYTHMIND_VERSION,
        "git_sha":    os.getenv("RHYTHMIND_GIT_SHA", "unknown"),
        "build_time": os.getenv("RHYTHMIND_BUILD_TIME", "unknown"),
        "env":        settings.env,
    }
