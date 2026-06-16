"""
audit/sinks.py — 审计事件 sink 抽象 + 三种实现

设计:
  - AuditSink 是 ABC，子类实现 `emit(record)`
  - 默认使用 StructlogSink（与现有日志体系一致；生产应叠加文件 / 远程 sink）
  - InMemorySink 仅用于测试，可断言事件被发出
  - S3JsonlSink 写 append-only S3 对象（按天分桶；用 Object Lock 实现"不可篡改"）

非阻塞契约:
  生产 sink 耗时 I/O 时必须通过 asyncio.create_task 排队，emit() 不阻塞主请求。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

logger = logging.getLogger(__name__)


# ── 数据结构 ────────────────────────────────────────────────────────────────

@dataclass
class AuditRecord:
    event: str
    user_id: str | None = None
    timestamp: float = field(default_factory=time.time)
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "event": self.event,
            "user_id": self.user_id,
            "timestamp": self.timestamp,
            **self.fields,
        }


# ── ABC ────────────────────────────────────────────────────────────────────

class AuditSink(ABC):
    """所有 sink 实现的基类。emit 必须永不抛异常（吞掉、降级到 stderr）。"""

    @abstractmethod
    def emit(self, record: AuditRecord) -> None: ...


# ── 1. structlog sink（默认）────────────────────────────────────────────────

class StructlogSink(AuditSink):
    """把审计事件写到 structlog 的 `audit` logger。生产应配置 sidecar 把
    JSON 行收到 ELK / Loki / CloudWatch。"""

    def __init__(self) -> None:
        try:
            import structlog
            self._log = structlog.get_logger("audit")
        except ImportError:
            self._log = logging.getLogger("audit")

    def emit(self, record: AuditRecord) -> None:
        try:
            payload = record.to_dict()
            self._log.info("audit", **payload)
        except Exception as exc:  # 永不抛
            logger.warning("audit.structlog_sink_failed event=%s error=%s", record.event, exc)  # noqa: E501


# ── 2. InMemory sink（测试用）──────────────────────────────────────────────

class InMemorySink(AuditSink):
    """只把事件累积到内存里，供单元测试断言。"""
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def emit(self, record: AuditRecord) -> None:
        self.records.append(record)

    def find(self, event: str) -> list[AuditRecord]:
        return [r for r in self.records if r.event == event]


# ── 3. S3 JSONL sink（生产推荐）────────────────────────────────────────────

class S3JsonlSink(AuditSink):
    """
    把每条事件 append 到 S3 上的按日分桶 JSONL 对象。

    要点:
      - 桶启用 Object Lock（Compliance 模式）才能算"不可篡改"
      - 事件先写本地 buffer（asyncio.Queue），后台 task 批量 flush，避免阻塞请求
      - boto3 是软依赖：未装时 sink 退化为 no-op + 启动时 WARN

    使用:
        sink = S3JsonlSink(bucket="rhythmind-audit", prefix="prod/")
        install_audit_sink(sink)
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        *,
        flush_interval: float = 5.0,
        max_buffer: int = 200,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.rstrip("/") + ("/" if prefix else "")
        self.flush_interval = flush_interval
        self.max_buffer = max_buffer

        try:
            import boto3
            self._client = boto3.client("s3")
        except ImportError:
            logger.warning(
                "audit.s3_sink_unavailable boto3 not installed — sink will be no-op"
            )
            self._client = None

        self._buffer: list[AuditRecord] = []
        self._task: Any = None  # 后台 flush task

    def emit(self, record: AuditRecord) -> None:
        if self._client is None:
            return  # no-op
        self._buffer.append(record)
        # 超过 max_buffer 立刻 flush；否则由后台 task 周期 flush
        if len(self._buffer) >= self.max_buffer:
            self._flush_now()
        else:
            self._ensure_background()

    def _ensure_background(self) -> None:
        if self._task is not None and not getattr(self._task, "done", lambda: True)():
            return
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            self._task = loop.create_task(self._periodic_flush())
        except RuntimeError:
            # 没有 running loop（非 async 环境），fallback 同步 flush
            self._flush_now()

    async def _periodic_flush(self) -> None:
        import asyncio
        while self._buffer:
            await asyncio.sleep(self.flush_interval)
            self._flush_now()

    def _flush_now(self) -> None:
        if not self._buffer or self._client is None:
            return
        records, self._buffer = self._buffer, []
        from datetime import datetime
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        key = f"{self.prefix}{day}/{int(time.time()*1000)}-{uuid.uuid4().hex[:8]}.jsonl"
        body = "\n".join(json.dumps(r.to_dict(), ensure_ascii=False, default=str)
                         for r in records).encode("utf-8")
        try:
            # 调用方需保证 bucket 已开启 Object Lock；
            # 这里不强行设 ObjectLock 以保持参数最小集，由 bucket 默认策略接管。
            self._client.put_object(Bucket=self.bucket, Key=key, Body=body)
        except Exception as exc:
            logger.warning("audit.s3_flush_failed key=%s error=%s", key, exc)
            # 失败时把记录放回 buffer 头部，下一轮重试（最多保留 max_buffer*2）
            self._buffer = (records + self._buffer)[: self.max_buffer * 2]
