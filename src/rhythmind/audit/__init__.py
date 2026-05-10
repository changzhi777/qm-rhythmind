# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Audit log package (R-3 in THREAT_MODEL.md)
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────
"""
audit — Tamper-evident operational audit log

公开 API:
  audit_log(event, **fields)        — 同步 + 异步通用入口
  AuditEvent                        — 事件类型常量
  install_audit_sink(sink)          — 替换默认 sink（生产指 S3 / SIEM）

事件类型（最小集合）：
  privacy.export         — 用户导出自己的数据
  privacy.delete         — 用户删除自己的数据
  mcp.unauthenticated    — MCP 端点在 mcp_require_auth=False 下被命中
  auth.bypass_used       — dev_auth_bypass 通道被使用
  config.unsafe_startup  — assert_production_safe() 拒启
  rate_limit.blocked     — 限流命中（高基数则跳过）
  privacy.delete_failure — 任一存储删除失败

约束:
  - 永不持久化 PII 原值（health_rate/steps/具体数值），只记 user_id + 操作元信息
  - 失败必须走静默降级（fallthrough 到 structlog），不能阻断业务
  - 任何 sink 实现都必须是非阻塞 fire-and-forget；耗时 I/O 走 background task
"""
from rhythmind.audit.events import AuditEvent  # noqa: F401
from rhythmind.audit.logger import audit_log, install_audit_sink, get_sink  # noqa: F401
from rhythmind.audit.sinks import (  # noqa: F401
    AuditSink,
    InMemorySink,
    StructlogSink,
    S3JsonlSink,
)
