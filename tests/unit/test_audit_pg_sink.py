"""
tests/unit/test_audit_pg_sink.py — PGSink 单元测试

策略：测试 emit 缓冲、批量触发、初始化参数。
_write_batch 依赖未创建的 db.models，仅测试其降级行为。
"""
from __future__ import annotations

from unittest.mock import MagicMock

from rhythmind.audit.pg_sink import PGSink
from rhythmind.audit.sinks import AuditRecord


def _make_record(event: str = "test.event") -> AuditRecord:
    return AuditRecord(event=event, user_id="u1")


class TestPGSinkInit:

    def test_default_params(self):
        sink = PGSink()
        assert sink.batch_size == 50
        assert sink.flush_interval == 5.0
        assert sink._buffer == []

    def test_custom_params(self):
        sink = PGSink(batch_size=100, flush_interval=10.0)
        assert sink.batch_size == 100
        assert sink.flush_interval == 10.0


class TestPGSinkEmit:

    def test_emit_buffers_record(self):
        sink = PGSink(batch_size=10)
        sink._flush_now = MagicMock()

        sink.emit(_make_record())
        assert len(sink._buffer) == 1
        sink._flush_now.assert_not_called()

    def test_emit_triggers_flush_at_batch_size(self):
        sink = PGSink(batch_size=2)
        sink._flush_now = MagicMock()

        sink.emit(_make_record("e1"))
        sink.emit(_make_record("e2"))
        assert sink._flush_now.call_count == 1

    def test_emit_records_contain_event_data(self):
        sink = PGSink(batch_size=100)
        sink._flush_now = MagicMock()

        sink.emit(_make_record("privacy.export"))
        assert sink._buffer[0]["event"] == "privacy.export"
        assert sink._buffer[0]["user_id"] == "u1"

    def test_multiple_emits_accumulate(self):
        sink = PGSink(batch_size=100)
        sink._flush_now = MagicMock()

        for i in range(5):
            sink.emit(_make_record(f"event.{i}"))
        assert len(sink._buffer) == 5


class TestPGSinkFlushNow:

    def test_flush_now_skips_empty_buffer(self):
        sink = PGSink()
        # Should not raise
        sink._flush_now()
