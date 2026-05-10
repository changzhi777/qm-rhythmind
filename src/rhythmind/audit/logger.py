"""
audit/logger.py — audit_log() 入口 + 模块级 sink 注册

设计:
  - 默认 sink = StructlogSink（与现有日志混在一起就可被 sidecar 收集）
  - install_audit_sink(sink) 替换为生产 sink（S3JsonlSink / 自定义）
  - audit_log(event, user_id=None, **fields) 是唯一入口；fire-and-forget
  - PII 兜底：对值做基础脱敏（trim 长字符串），但调用方仍负主要责任
"""
from __future__ import annotations

import logging
from typing import Any

from rhythmind.audit.sinks import AuditRecord, AuditSink, StructlogSink

logger = logging.getLogger(__name__)

# ── 模块级 sink 单例 ────────────────────────────────────────────────────────
_sink: AuditSink = StructlogSink()


# 防止把超长字段（误传整个请求体）打进审计存储
_MAX_VALUE_CHARS = 512


def install_audit_sink(sink: AuditSink) -> None:
    """替换全局 sink。生产在 lifespan 中调用一次。"""
    global _sink
    _sink = sink
    logger.info("audit.sink_installed kind=%s", sink.__class__.__name__)


def get_sink() -> AuditSink:
    return _sink


def audit_log(event: str, *, user_id: str | None = None, **fields: Any) -> None:
    """
    发一条审计事件。永不抛异常，永不阻塞。

    Examples:
        audit_log(AuditEvent.PRIVACY_DELETE, user_id="alice", successes=4, failures=0)
        audit_log(AuditEvent.AUTH_BYPASS_USED, user_id="alice", env="dev")
    """
    try:
        clean = {k: _clip(v) for k, v in fields.items()}
        record = AuditRecord(event=event, user_id=user_id, fields=clean)
        _sink.emit(record)
    except Exception as exc:
        logger.warning("audit.dispatch_failed event=%s error=%s", event, exc)


def _clip(v: Any) -> Any:
    """超长字符串截短；其它类型透传。"""
    if isinstance(v, str) and len(v) > _MAX_VALUE_CHARS:
        return v[:_MAX_VALUE_CHARS] + f"...<truncated {len(v) - _MAX_VALUE_CHARS}>"
    return v
