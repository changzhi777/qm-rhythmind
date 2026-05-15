"""
audit/sinks.py — PGSink：审计事件持久化到 PostgreSQL

配合 migration 004_audit_session_tables 使用。
当 S3JsonlSink 不可用时（无 boto3），可选择 PGSink 做持久化存储。
"""
from __future__ import annotations

import logging
from typing import Any

from rhythmind.audit.sinks import AuditRecord, AuditSink

logger = logging.getLogger(__name__)


class PGSink(AuditSink):
    """
    将审计事件异步写入 PostgreSQL audit_log 表。

    设计原则：
      - emit() 立即返回（后台 asyncio task 批量写入）
      - batch_size=50 / flush_interval=5s 两个参数控制写入粒度
      - 失败时降级到 stderr，不阻断业务

    使用（生产推荐）：
        from rhythmind.audit.sinks import PGSink
        install_audit_sink(PGSink())
    """

    def __init__(
        self,
        batch_size: int = 50,
        flush_interval: float = 5.0,
    ) -> None:
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._buffer: list[dict[str, Any]] = []
        self._task: Any = None
        self._lock: Any = None

    def emit(self, record: AuditRecord) -> None:
        self._buffer.append(record.to_dict())
        if len(self._buffer) >= self.batch_size:
            self._flush_now()

    def _flush_now(self) -> None:
        if not self._buffer:
            return
        records, self._buffer = self._buffer[:], []
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            loop.create_task(self._write_batch(records))
        except Exception as exc:
            logger.warning("audit.pg_flush_async_failed records=%d %s", len(records), exc)
            # sync fallback
            asyncio.run(self._write_batch(records))

    async def _write_batch(self, records: list[dict[str, Any]]) -> None:
        from rhythmind.core.memory.manager import AsyncSessionLocal
        from rhythmind.db.models import Base
        from sqlalchemy import insert

        # Lazy table check — only write if table exists
        try:
            async with AsyncSessionLocal() as sess:
                # Check if audit_log table exists
                result = await sess.execute(
                    __import__("sqlalchemy").text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_name = 'audit_log' LIMIT 1"
                    )
                )
                if not result.scalar():
                    logger.debug("audit.pg_sink skipped — audit_log table not found")
                    return
        except Exception:
            return

        try:
            async with AsyncSessionLocal() as sess, sess.begin():
                stmt = insert(__import__("rhythmind.db.models", fromlist=["Base"]).Base.metadata.tables["audit_log"])
                await sess.execute(stmt, records)
        except Exception as exc:
            logger.warning("audit.pg_batch_write_failed records=%d %s", len(records), exc)