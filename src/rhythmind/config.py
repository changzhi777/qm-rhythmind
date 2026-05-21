# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
config.py — 统一配置入口（pydantic-settings，.env 优先）

环境变量命名规范：全大写，与字段名一致。
生产部署只需在容器环境注入对应 ENV，无需修改代码。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── 运行模式 ─────────────────────────────────────────────────────────
    env: Literal["dev", "test", "prod"] = "dev"
    debug: bool = False

    # ── LiteLLM proxy ────────────────────────────────────────────────────
    litellm_url: str = "http://localhost:4000"
    litellm_master_key: str = Field(default="sk-1234", repr=False)

    # 模型别名（对应 litellm_config.yaml 中的 model_name）
    model_primary: str = "primary"       # claude-sonnet-4-6  — 高质量推理
    model_fast: str = "fast"             # deepseek-chat       — 快速/廉价
    model_local: str = "local"           # qwen2.5:7b          — 本地备用
    model_compliance: str = "compliance" # gemma-4-e4b (omlX) — prompt 合规审查

    # ── Model Adapter 路由规范（优先于 LiteLLM 别名）────────────────────
    # 格式：
    #   "mlx://<hf_repo>"        → MLXAdapter（本地 Apple Silicon 推理）
    #   "omlX://<model_name>"    → OMLXAdapter（本地 oMLX 服务）
    #   其他字符串               → LiteLLMAdapter（透传给 LiteLLM proxy）
    #
    # 空字符串 = 回退到 model_primary / model_compliance LiteLLM 别名
    model_primary_spec: str = "mlx://mlx-community/Qwen3-30B-A3B-4bit"
    model_compliance_spec: str = "omlX://gemma-4-e4b-it-4bit"

    # MLX 推理参数
    mlx_thinking_mode: bool = False       # Qwen3 thinking 模式，默认关闭（速度优先）
    mlx_max_tokens: int = 2048
    mlx_temperature: float = 0.3
    mlx_semaphore_limit: int = 1          # M4 16GB：同时只跑 1 个重型推理

    # oMLX 本地模型服务
    omlX_base_url: str = "http://localhost:8000"
    omlX_api_key: str = Field(default="ak47", repr=False)

    # 合规审查器行为开关
    compliance_audit_enabled: bool = True   # 生产 True，压测时可临时关闭
    compliance_audit_timeout: float = 8.0   # gemma 本地推理超时（秒）
    # 审查器判定 BLOCK 的最低风险分（0-1），超过则拦截
    compliance_audit_block_score: float = 0.75
    compliance_audit_warn_score: float = 0.40

    # ── 数据库（PostgreSQL 生产 / SQLite 单元测试）──────────────────────
    database_url: str = (
        "postgresql+asyncpg://rhythmind:rhythmind@localhost:5432/rhythmind"
    )
    # 单元测试覆盖：sqlite+aiosqlite:///:memory:

    # PostgreSQL 连接池参数
    #
    # 调优原则：
    #   pool_size        — 常驻连接数 = CPU cores * 2 ~ 10（HTTP 无状态，10 够用）
    #   max_overflow     — 峰值额外连接，30 并发用户时 → 每人 1 连接有余
    #   pool_timeout     — 30s 足够，避免瞬时排队时用户体感超时
    #   pool_recycle     — 1800s < PG idle_timeout(默认 30min)，防止被服务端踢掉
    #   pool_pre_ping    — 取连接前 ping 一下，保证连接活性（新增）
    pg_pool_size: int = 10
    pg_pool_max_overflow: int = 20
    pg_pool_timeout: float = 30.0
    pg_pool_recycle: int = 1800
    pg_pool_pre_ping: bool = True  # 健康检查：取连接前验证活性，避免断连误用

    # ── Redis ────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379"
    redis_pool_size: int = 10

    # ── InfluxDB（可穿戴流数据）─────────────────────────────────────────
    influxdb_url: str = "http://localhost:8086"
    influxdb_token: str = Field(default="", repr=False)
    influxdb_org: str = "rhythmind"
    influxdb_bucket: str = "health_metrics"

    # ── QMD（本地语义搜索）──────────────────────────────────────────────
    qmd_url: str = "http://localhost:8181"
    qmd_timeout: float = 5.0
    qmd_top_k: int = 3   # 精准召回，控制 token 消耗

    # ── 合规阈值 ─────────────────────────────────────────────────────────
    compliance_pass_threshold: float = 0.75    # >= PASS
    compliance_warn_threshold: float = 0.50    # [0.50, 0.75) → WARN + disclaimer
    # < 0.50 → BLOCK，拒绝输出

    # ── LoopGuard（防 RehabAgent 无限循环）──────────────────────────────
    loop_guard_ttl_hours: int = 24
    loop_guard_max_calls: int = 3  # 同 user+intent 24h 内最多触发次数

    # ── JWT ──────────────────────────────────────────────────────────────
    jwt_secret: str = Field(default="change-me-in-prod", repr=False)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24h

    # ── 外部 API Keys（可选，透传给 LiteLLM）────────────────────────────
    anthropic_api_key: str = Field(default="", repr=False)
    deepseek_api_key: str = Field(default="", repr=False)

    # ── Sentry ───────────────────────────────────────────────────────────
    sentry_dsn: str = ""

    # ── Langfuse LLM 可观测性 ────────────────────────────────────────────
    langfuse_enabled: bool = False
    langfuse_public_key: str = Field(default="", repr=False)
    langfuse_secret_key: str = Field(default="", repr=False)
    langfuse_host: str = "http://localhost:3020"
    langfuse_db_url: str = Field(
        default="",
        repr=False,
        description="直查 Langfuse PG 的连接串（只读聚合查询）",
    )

    # ── 鉴权开发便利开关（仅本地）────────────────────────────────────────
    # True 时 deps.get_current_user_id() 接受明文 user_id 作为 Bearer token。
    # 必须显式开启，且 ENV=prod 时强制为 False（startup 直接抛错拒绝运行）。
    dev_auth_bypass: bool = False

    # ── CORS（前端域名白名单，逗号分隔）─────────────────────────────────
    # 例：CORS_ALLOW_ORIGINS="https://app.rhythmind.ai,https://admin.rhythmind.ai"
    # ENV=dev 时若留空则放行 http://localhost 系列。
    cors_allow_origins: str = ""

    # ── Alembic 迁移开关（容器启动时自动跑 upgrade head）────────────────
    run_migrations_on_startup: bool = False

    # ── 启动断言：模型 spec 与运行平台一致 ──────────────────────────────
    # True 时若 model_primary_spec 以 mlx:// 开头但当前不是 Apple Silicon，
    # 启动直接报错，避免容器化部署因 MLX 不可用而运行时崩溃。
    enforce_model_platform: bool = True

    # ── MCP 端点鉴权 ────────────────────────────────────────────────────
    # True (default): /mcp/sse 与 /mcp/messages/ 走 CurrentUserId 依赖；
    # False: 不强制鉴权 —— 仅允许在受信任的本地/私网环境使用，
    #        ENV=prod 时强制为 True（assert_production_safe 会拒启）。
    mcp_require_auth: bool = True

    # ── 请求体大小硬上限（字节）─────────────────────────────────────────
    # 中间件在读 body 之前用 Content-Length 拒绝；0 表示禁用（不推荐）。
    max_request_body_bytes: int = 1_048_576  # 1 MiB

    # ── /readyz 上游 LLM 检查（可选，避免每次探针都打第三方）────────────
    # True 时 /readyz 会顺带 ping LiteLLM 与 oMLX；任一不可达 -> 503
    # 默认关闭：DB / Redis 已经足够代表"准备好接流量"，LLM 上游用 Alert 监控更省成本
    readyz_check_llm_upstream: bool = False
    readyz_llm_timeout: float = 2.0

    # ── Skill 审核（v0.1.6+）─────────────────────────────────────────────
    # True 时 SkillEngine 新提取的 skill 进入 status='pending'，
    # 必须 admin 通过 /admin/skills/{hash}/approve 后才会推到 QMD 被检索；
    # False 时保持旧行为（直接 approved 并推 QMD）。
    skill_require_approval: bool = False

    # admin 用户白名单（user_id 逗号分隔）。空 = 没有 admin。
    # 例：ADMIN_USER_IDS="alice,bob"
    admin_user_ids: str = ""

    # ── AgentPool（LRU 实例缓存）────────────────────────────────────────
    # 控制同一时刻最多缓存多少用户的 Agent 实例
    agent_pool_max_users: int = 500
    # Agent 实例空闲 TTL（秒），超过后被清理
    agent_pool_ttl: float = 1800.0

    # ── 危险默认值黑名单（任何一个出现在生产即拒绝启动）───────────────
    _SECRET_DEFAULTS_BLOCKLIST = frozenset({
        "change-me-in-prod",
        "change-me-to-random-256bit-string",
        "dev-secret-change-in-prod",
        "sk-1234",
        "sk-test",
        "dev-token-change-me",
        "test-secret",
        "rhythmind",   # postgres 默认密码
    })

    @field_validator("compliance_pass_threshold")
    @classmethod
    def validate_thresholds(cls, v: float) -> float:
        if not (0.0 < v <= 1.0):
            raise ValueError("compliance_pass_threshold must be in (0, 1]")
        return v

    def assert_production_safe(self) -> None:
        """
        生产部署前置断言。在 lifespan startup 中调用：
          - JWT secret 不是常见默认值
          - LiteLLM master key 不是 sk-1234 / sk-test
          - InfluxDB token 已设置
          - dev_auth_bypass 必须为 False
          - mlx:// 推理 spec 必须运行在 Apple Silicon 上

        任何一项不满足直接 raise，进程不会进入 serving 状态。
        """
        if self.env != "prod":
            return

        problems: list[str] = []

        if self.dev_auth_bypass:
            problems.append("dev_auth_bypass=True is forbidden when ENV=prod")

        if not self.mcp_require_auth:
            problems.append(
                "mcp_require_auth=False is forbidden when ENV=prod "
                "(MCP endpoints would be unauthenticated)"
            )

        if self.jwt_secret in self._SECRET_DEFAULTS_BLOCKLIST or len(self.jwt_secret) < 32:
            problems.append(
                "jwt_secret must be a strong random string (>=32 chars), "
                "not a known default"
            )

        if self.litellm_master_key in self._SECRET_DEFAULTS_BLOCKLIST:
            problems.append("litellm_master_key uses a known default value")

        if not self.influxdb_token or self.influxdb_token in self._SECRET_DEFAULTS_BLOCKLIST:
            problems.append("influxdb_token is empty or uses a known default")

        if "rhythmind:rhythmind@" in self.database_url:
            problems.append(
                "database_url contains the default 'rhythmind:rhythmind' credentials"
            )

        if self.enforce_model_platform and self.model_primary_spec.startswith("mlx://"):
            import platform
            mach = platform.machine().lower()
            sysname = platform.system().lower()
            if not (sysname == "darwin" and mach in {"arm64", "aarch64"}):
                problems.append(
                    f"model_primary_spec='{self.model_primary_spec}' requires Apple Silicon "
                    f"(macOS arm64), but running on {sysname}/{mach}. "
                    "Override with OMLX_SPEC=omlX://... or a LiteLLM alias."
                )

        if problems:
            raise RuntimeError(
                "Production startup blocked by unsafe configuration:\n  - "
                + "\n  - ".join(problems)
            )

    @property
    def admin_user_ids_set(self) -> set[str]:
        """解析 ADMIN_USER_IDS 为 set[str]，空字符串返回空 set。"""
        return {x.strip() for x in self.admin_user_ids.split(",") if x.strip()}

    @property
    def cors_origins_list(self) -> list[str]:
        """解析 cors_allow_origins 为列表。dev 环境下默认放行 localhost。"""
        if self.cors_allow_origins:
            return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]
        if self.env == "dev":
            return [
                "http://localhost",
                "http://localhost:3000",
                "http://localhost:3001",
                "http://localhost:5173",
                "http://127.0.0.1:3000",
                "http://127.0.0.1:3001",
            ]
        return []

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def litellm_base_url(self) -> str:
        return f"{self.litellm_url}/v1"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例，避免重复解析 .env 文件。测试时可 mock 替换。"""
    return Settings()


# 模块级快捷引用（大多数模块只需 `from rhythmind.config import settings`）
settings: Settings = get_settings()
