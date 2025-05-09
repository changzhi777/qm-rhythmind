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
    model_compliance: str = "compliance" # gemma-4-e4b (ollama) — prompt 合规审查

    # ── Model Adapter 路由规范（优先于 LiteLLM 别名）────────────────────
    # 格式：
    #   "mlx://<hf_repo>"        → MLXAdapter（本地 Apple Silicon 推理）
    #   "ollama://<model_name>"  → OllamaAdapter（Ollama HTTP）
    #   其他字符串               → LiteLLMAdapter（透传给 LiteLLM proxy）
    #
    # 空字符串 = 回退到 model_primary / model_compliance LiteLLM 别名
    model_primary_spec: str = "mlx://mlx-community/Qwen3-30B-A3B-4bit"
    model_compliance_spec: str = "ollama://gemma3:4b"

    # MLX 推理参数
    mlx_thinking_mode: bool = False       # Qwen3 thinking 模式，默认关闭（速度优先）
    mlx_max_tokens: int = 2048
    mlx_temperature: float = 0.3
    mlx_semaphore_limit: int = 1          # M4 16GB：同时只跑 1 个重型推理

    # Ollama 服务地址（compliance 审查专用，也可作本地备用）
    ollama_base_url: str = "http://localhost:11434"

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
    pg_pool_size: int = 10          # 常驻连接数
    pg_pool_max_overflow: int = 20  # 峰值溢出连接数（总上限 30）
    pg_pool_timeout: float = 30.0   # 等待连接超时（秒）
    pg_pool_recycle: int = 1800     # 连接最长存活时间（秒），防止 PG idle timeout

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

    @field_validator("compliance_pass_threshold")
    @classmethod
    def validate_thresholds(cls, v: float) -> float:
        if not (0.0 < v <= 1.0):
            raise ValueError("compliance_pass_threshold must be in (0, 1]")
        return v

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
