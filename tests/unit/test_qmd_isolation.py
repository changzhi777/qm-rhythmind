"""
tests/unit/test_qmd_isolation.py — QMD 命名空间安全隔离测试

核心安全红线：
  user_A 的集合操作不能被 user_B 访问
  _enforce_namespace() 在任何跨用户操作时必须抛出 SecurityError
"""
import pytest

from rhythmind.core.qmd.client import QMDClient, SecurityError, _user_collection


class TestEnforceNamespace:
    """_enforce_namespace() 单元测试"""

    def test_public_collection_passthrough(self):
        """非 user_ 前缀的公共集合直接放行。"""
        client = QMDClient.__new__(QMDClient)
        result = client._enforce_namespace("agent_skills", user_ns="")
        assert result == "agent_skills"

    def test_public_collection_ignores_user_ns(self):
        """公共集合即使传了 user_ns 也直接放行。"""
        client = QMDClient.__new__(QMDClient)
        result = client._enforce_namespace("health_knowledge", user_ns="user_x")
        assert result == "health_knowledge"

    def test_user_collection_correct_namespace(self):
        """正确 namespace 的 user 集合放行。"""
        client = QMDClient.__new__(QMDClient)
        collection = "user_alice123_memory"
        result = client._enforce_namespace(collection, user_ns="alice123")
        assert result == collection

    def test_user_collection_missing_user_ns_raises(self):
        """user_ 前缀集合但未提供 user_ns → SecurityError。"""
        client = QMDClient.__new__(QMDClient)
        with pytest.raises(SecurityError, match="requires user_ns"):
            client._enforce_namespace("user_alice_memory", user_ns="")

    def test_user_collection_wrong_user_raises(self):
        """user_alice 集合被 user_bob 访问 → SecurityError。"""
        client = QMDClient.__new__(QMDClient)
        with pytest.raises(SecurityError, match="namespace mismatch"):
            client._enforce_namespace("user_alice_memory", user_ns="bob")

    def test_user_collection_partial_match_raises(self):
        """user_ali 不能匹配 user_alice（防前缀欺骗）。"""
        client = QMDClient.__new__(QMDClient)
        with pytest.raises(SecurityError):
            client._enforce_namespace("user_alice_memory", user_ns="ali")

    def test_special_chars_in_user_id_sanitized(self):
        """特殊字符在 user_id 中被替换为下划线，但仍能正确匹配。"""
        client = QMDClient.__new__(QMDClient)
        # user_id 含特殊字符
        user_id = "user@example.com"
        collection = _user_collection(user_id, "memory")
        # 应可以正常放行（因为 _user_collection 已做 sanitize）
        result = client._enforce_namespace(collection, user_ns=user_id)
        assert "memory" in result

    def test_sql_injection_attempt_in_collection(self):
        """防止通过 collection 名注入。"""
        client = QMDClient.__new__(QMDClient)
        malicious = "user_alice_memory'; DROP TABLE agent_memory; --"
        with pytest.raises(SecurityError):
            client._enforce_namespace(malicious, user_ns="bob")


class TestUserCollection:
    """_user_collection() 辅助函数测试"""

    def test_normal_user_id(self):
        result = _user_collection("alice123", "memory")
        assert result == "user_alice123_memory"

    def test_special_chars_sanitized(self):
        result = _user_collection("alice@example.com", "memory")
        # @ 和 . 替换为 _
        assert result.startswith("user_")
        assert "memory" in result
        assert "@" not in result
        assert "." not in result

    def test_different_suffixes(self):
        assert _user_collection("u1", "memory") == "user_u1_memory"
        assert _user_collection("u1", "sessions") == "user_u1_sessions"
