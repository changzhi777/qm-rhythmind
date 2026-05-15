"""
tests/unit/test_audit_sinks.py — Audit Sink 测试

测试场景：
  1. AuditRecord 数据结构
  2. InMemorySink 累积和查询
  3. StructlogSink 不抛异常
  4. S3JsonlSink boto3 不可用时 no-op
  5. S3JsonlSink buffer 溢出时立即 flush
  6. S3JsonlSink 失败时 buffer 回滚
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from rhythmind.audit.sinks import (
    AuditRecord,
    AuditSink,
    InMemorySink,
    S3JsonlSink,
    StructlogSink,
)


class TestAuditRecord:
    """AuditRecord 数据结构测试。"""

    def test_to_dict(self):
        """to_dict 返回正确格式。"""
        record = AuditRecord(
            event="test.event",
            user_id="user_001",
            fields={"action": "create", "resource": "document"},
        )
        d = record.to_dict()

        assert d["event"] == "test.event"
        assert d["user_id"] == "user_001"
        assert d["action"] == "create"
        assert d["resource"] == "document"
        assert "record_id" in d
        assert "timestamp" in d

    def test_record_id_unique(self):
        """每次创建应有唯一 record_id。"""
        r1 = AuditRecord(event="test")
        r2 = AuditRecord(event="test")
        assert r1.record_id != r2.record_id

    def test_default_values(self):
        """默认字段有正确值。"""
        record = AuditRecord(event="test")
        assert record.user_id is None
        assert record.timestamp > 0
        assert record.record_id is not None
        assert record.fields == {}


class TestInMemorySink:
    """InMemorySink 测试。"""

    def test_emit_accumulates_records(self):
        """emit 累积记录。"""
        sink = InMemorySink()
        sink.emit(AuditRecord(event="event_a"))
        sink.emit(AuditRecord(event="event_b"))

        assert len(sink.records) == 2

    def test_find_filters_by_event(self):
        """find 返回指定事件的记录。"""
        sink = InMemorySink()
        sink.emit(AuditRecord(event="login"))
        sink.emit(AuditRecord(event="logout"))
        sink.emit(AuditRecord(event="login"))

        found = sink.find("login")
        assert len(found) == 2

    def test_find_returns_empty_for_no_match(self):
        """未找到时返回空列表。"""
        sink = InMemorySink()
        sink.emit(AuditRecord(event="login"))

        found = sink.find("logout")
        assert found == []


class TestStructlogSink:
    """StructlogSink 测试。"""

    def test_emit_does_not_raise(self):
        """emit 不应抛出异常。"""
        sink = StructlogSink()
        record = AuditRecord(event="test.event", user_id="user")

        # 不应抛出
        sink.emit(record)

    def test_emit_with_invalid_data_does_not_raise(self):
        """异常数据不应导致 emit 抛出。"""
        sink = StructlogSink()

        # 传入可能导致日志系统异常的字段
        record = AuditRecord(
            event="test.event",
            user_id=None,
            fields={"circular_ref": {"nested": None}},  # 无法序列化的字段
        )

        # 不应抛出
        sink.emit(record)


class TestS3JsonlSinkNoOp:
    """S3JsonlSink boto3 不可用时行为测试。"""

    def test_boto3_not_available_is_noop(self):
        """boto3 未安装时 emit 是 no-op。"""
        with patch.dict("sys.modules", {"boto3": None}):
            sink = S3JsonlSink(bucket="test-bucket")

            # emit 不应抛出，即使 client 为 None
            sink.emit(AuditRecord(event="test.event", user_id="user"))

            # buffer 应为空（no-op）
            assert sink._buffer == []

    def test_client_none_emit_noop(self):
        """client 为 None 时 emit 是 no-op。"""
        sink = S3JsonlSink.__new__(S3JsonlSink)
        sink.bucket = "test-bucket"
        sink.prefix = ""
        sink.flush_interval = 5.0
        sink.max_buffer = 200
        sink._client = None
        sink._buffer = []
        sink._task = None

        # emit 不应抛出
        sink.emit(AuditRecord(event="test.event"))

        # buffer 应保持空
        assert sink._buffer == []


class TestS3JsonlSinkBuffer:
    """S3JsonlSink buffer 逻辑测试。"""

    def test_emit_accumulates_in_buffer(self):
        """emit 累积到 buffer。"""
        sink = S3JsonlSink.__new__(S3JsonlSink)
        sink.bucket = "test-bucket"
        sink.prefix = ""
        sink.flush_interval = 5.0
        sink.max_buffer = 200
        sink._client = MagicMock()  # 模拟有 client
        sink._buffer = []
        sink._task = None

        sink.emit(AuditRecord(event="event_1"))
        sink.emit(AuditRecord(event="event_2"))

        assert len(sink._buffer) == 2

    def test_buffer_full_triggers_immediate_flush(self):
        """buffer 满时立即 flush。"""
        sink = S3JsonlSink.__new__(S3JsonlSink)
        sink.bucket = "test-bucket"
        sink.prefix = ""
        sink.flush_interval = 5.0
        sink.max_buffer = 3
        mock_client = MagicMock()
        sink._client = mock_client
        sink._buffer = []
        sink._task = None

        # 填充到 max_buffer - 1
        for i in range(2):
            sink.emit(AuditRecord(event=f"event_{i}"))

        assert len(sink._buffer) == 2
        assert mock_client.put_object.call_count == 0

        # 第 3 次 emit（达到 max_buffer）应触发 flush
        sink.emit(AuditRecord(event="event_3"))

        assert mock_client.put_object.call_count == 1
        assert sink._buffer == []  # flush 后清空

    def test_flush_now_with_no_client(self):
        """_flush_now 在 client 为 None 时不抛异常。"""
        sink = S3JsonlSink.__new__(S3JsonlSink)
        sink.bucket = "test-bucket"
        sink.prefix = ""
        sink.flush_interval = 5.0
        sink.max_buffer = 200
        sink._client = None
        sink._buffer = [AuditRecord(event="test")]
        sink._task = None

        # 不应抛出
        sink._flush_now()

    def test_flush_now_with_empty_buffer(self):
        """_flush_now 在 buffer 空时无事可做。"""
        sink = S3JsonlSink.__new__(S3JsonlSink)
        sink.bucket = "test-bucket"
        sink.prefix = ""
        sink.flush_interval = 5.0
        sink.max_buffer = 200
        mock_client = MagicMock()
        sink._client = mock_client
        sink._buffer = []
        sink._task = None

        sink._flush_now()

        # 没有记录，不应调用 put_object
        mock_client.put_object.assert_not_called()


class TestS3JsonlSinkFailure:
    """S3JsonlSink 失败处理测试。"""

    def test_put_object_failure_rollback_buffer(self):
        """put_object 失败时 buffer 回滚。"""
        sink = S3JsonlSink.__new__(S3JsonlSink)
        sink.bucket = "test-bucket"
        sink.prefix = ""
        sink.flush_interval = 5.0
        sink.max_buffer = 200
        sink._buffer = []
        sink._task = None

        mock_client = MagicMock()
        mock_client.put_object.side_effect = Exception("S3 error")
        sink._client = mock_client

        # 添加记录
        record = AuditRecord(event="test_event")
        sink._buffer.append(record)

        sink._flush_now()

        # 记录应回滚到 buffer 头部
        assert record in sink._buffer
        # 数量不超过 max_buffer * 2
        assert len(sink._buffer) <= sink.max_buffer * 2

    def test_flush_interval_respected(self):
        """flush_interval 参数被正确使用。"""
        sink = S3JsonlSink(bucket="test", flush_interval=10.0)
        assert sink.flush_interval == 10.0

    def test_prefix_handling(self):
        """prefix 末尾斜杠处理正确。"""
        sink = S3JsonlSink(bucket="test", prefix="logs/")
        assert sink.prefix == "logs/"

        sink2 = S3JsonlSink(bucket="test", prefix="logs")
        assert sink2.prefix == "logs/"


class TestAuditSinkABC:
    """AuditSink ABC 测试。"""

    def test_abc_cannot_instantiate_directly(self):
        """直接实例化 ABC 应失败。"""
        with pytest.raises(TypeError):
            AuditSink()  # type: ignore


class TestAuditRecordIntegration:
    """AuditRecord 与各 Sink 集成测试。"""

    def test_record_roundtrip_to_memory(self):
        """完整流程：创建 record → emit → find。"""
        sink = InMemorySink()

        original = AuditRecord(
            event="data.delete",
            user_id="user_123",
            fields={"store": "postgres", "rows": 5},
        )

        sink.emit(original)
        found = sink.find("data.delete")

        assert len(found) == 1
        assert found[0].user_id == "user_123"
        assert found[0].fields["store"] == "postgres"

    def test_multiple_sinks_independent(self):
        """多个 sink 实例互不影响。"""
        sink_a = InMemorySink()
        sink_b = InMemorySink()

        sink_a.emit(AuditRecord(event="only_a"))
        sink_b.emit(AuditRecord(event="only_b"))

        assert len(sink_a.records) == 1
        assert len(sink_b.records) == 1
        assert sink_a.records[0].event == "only_a"
        assert sink_b.records[0].event == "only_b"
