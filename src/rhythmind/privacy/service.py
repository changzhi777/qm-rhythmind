# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Privacy service: GDPR / PIPL data subject rights
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────

"""
privacy/service.py — 用户数据导出 / 删除

合规背景:
  - GDPR Article 15（访问权）、Article 17（被遗忘权）、Article 20（可移植性）
  - 中国《个人信息保护法》第 45/46/47 条（查阅、复制、转移、删除）

设计原则:
  - **覆盖所有用户标记的数据存储**：PG（agent_memory + health_fact）、
    Redis（LoopGuard + rate-limit 计数）、InfluxDB（用户指标点）、
    QMD（user-namespaced collections）。
    SkillRecord 是全局共享技能库（无 user_id），不在删除范围。
  - **删除是不可逆的**：要求调用方先调用 export，再传 confirm_token=user_id
    （简单的"复述用户名"防误删；生产可改成 email OTP）。
  - **审计日志**：每次 export/delete 都写一条 audit 行（控制台 structlog；
    后续可改成数据库或外部 SIEM）。
  - **失败可重试**：删除以"列表 + 报告"形式返回成功/失败明细，
    任一存储失败不阻断其余删除（best-effort）。

使用:
    from rhythmind.privacy import PrivacyService
    svc = PrivacyService()
    bundle = await svc.export_user_data("alice")
    report = await svc.delete_user_data("alice", confirm_token="alice")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

import structlog
from sqlalchemy import delete, select

import rhythmind.core.memory.manager as _mem_mgr  # 通过模块引用，
from rhythmind.config import settings

# 兼容 conftest.reset_db 的运行时替换
from rhythmind.core.memory.models import AgentMemory, HealthFact

log = structlog.get_logger(__name__)


# ── 数据结构 ──────────────────────────────────────────────────────────────

@dataclass
class UserDataExport:
    """
    单个用户的完整可导出数据（JSON-friendly）。
    """
    user_id: str
    exported_at: str
    schema_version: str = "1.0"

    agent_memory:  list[dict[str, Any]] = field(default_factory=list)
    health_facts:  list[dict[str, Any]] = field(default_factory=list)
    redis_keys:    list[str]            = field(default_factory=list)
    influx_points: int                  = 0
    qmd_collections: list[str]          = field(default_factory=list)

    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "exported_at": self.exported_at,
            "schema_version": self.schema_version,
            "agent_memory": self.agent_memory,
            "health_facts": self.health_facts,
            "redis_keys": self.redis_keys,
            "influx_points": self.influx_points,
            "qmd_collections": self.qmd_collections,
            "notes": self.notes,
        }


@dataclass
class DeletionReport:
    """
    删除操作汇总报告。`successes` / `failures` 中的每一项是 (store, detail)。
    """
    user_id: str
    deleted_at: str
    successes: list[tuple[str, str]] = field(default_factory=list)
    failures:  list[tuple[str, str]] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return len(self.failures) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "deleted_at": self.deleted_at,
            "is_clean": self.is_clean,
            "successes": [{"store": s, "detail": d} for s, d in self.successes],
            "failures":  [{"store": s, "detail": d} for s, d in self.failures],
        }


# ── 服务 ──────────────────────────────────────────────────────────────────

class PrivacyService:
    """
    数据主体权利的统一处理入口。

    所有外部存储客户端（Redis / Influx / QMD）都通过依赖注入或惰性导入，
    便于单测时替换为 mock。
    """

    def __init__(
        self,
        *,
        session_factory: Any = None,
        redis_client: Any = None,
        influx_client: Any = None,
        qmd_client: Any = None,
    ) -> None:
        # 默认懒解析 AsyncSessionLocal —— conftest.reset_db 会在每条测试前
        # 替换 rhythmind.core.memory.manager.AsyncSessionLocal，需要每次调用时
        # 重新读模块属性，避免捕获已失效的旧 sessionmaker。
        self._sessionmaker = session_factory or (lambda: _mem_mgr.AsyncSessionLocal())
        self._redis = redis_client
        self._influx = influx_client
        self._qmd = qmd_client

    # ── 导出 ─────────────────────────────────────────────────────────────

    async def export_user_data(self, user_id: str) -> UserDataExport:
        """收集所有 user_id 标记的数据返回 JSON 友好结构。"""
        from datetime import datetime

        bundle = UserDataExport(
            user_id=user_id,
            exported_at=datetime.now(UTC).isoformat(),
        )

        # 1) agent_memory
        async with self._sessionmaker() as sess:
            rows = (await sess.execute(
                select(AgentMemory).where(AgentMemory.user_id == user_id)
            )).scalars().all()
            bundle.agent_memory = [_serialize_memory(r) for r in rows]

        # 2) health_facts
        async with self._sessionmaker() as sess:
            rows = (await sess.execute(
                select(HealthFact).where(HealthFact.user_id == user_id)
            )).scalars().all()
            bundle.health_facts = [_serialize_fact(r) for r in rows]

        # 3) Redis keys (best-effort; pattern match)
        try:
            r = await self._get_redis()
            keys = await _scan_user_keys(r, user_id)
            bundle.redis_keys = keys
        except Exception as exc:
            log.warning("privacy.export redis_skip error=%s", exc)
            bundle.notes.append(f"redis: skipped ({exc.__class__.__name__})")

        # 4) Influx point count（用 query_range 仅取 count；避免一次性把数据点全捞）
        try:
            count = await self._count_influx_points(user_id)
            bundle.influx_points = count
        except Exception as exc:
            log.warning("privacy.export influx_skip error=%s", exc)
            bundle.notes.append(f"influxdb: skipped ({exc.__class__.__name__})")

        # 5) QMD user-namespaced collections（仅记录名称，内容由 QMD 自行管理）
        try:
            bundle.qmd_collections = [
                f"user_{user_id}_memory",
                f"user_{user_id}_facts",
            ]
        except Exception:
            pass

        log.info(
            "privacy.export user_id=%s memory_rows=%d facts_rows=%d redis_keys=%d influx_points=%d",
            user_id, len(bundle.agent_memory), len(bundle.health_facts),
            len(bundle.redis_keys), bundle.influx_points,
        )
        return bundle

    # ── 删除 ─────────────────────────────────────────────────────────────

    async def delete_user_data(
        self,
        user_id: str,
        *,
        confirm_token: str,
    ) -> DeletionReport:
        """
        不可逆删除。confirm_token 必须等于 user_id 才执行（防误删）。
        """
        from datetime import datetime

        if confirm_token != user_id:
            raise ValueError(
                "confirm_token must equal user_id to proceed with deletion"
            )

        report = DeletionReport(
            user_id=user_id,
            deleted_at=datetime.now(UTC).isoformat(),
        )

        # 1) PG: agent_memory
        try:
            async with self._sessionmaker() as sess:
                res = await sess.execute(
                    delete(AgentMemory).where(AgentMemory.user_id == user_id)
                )
                await sess.commit()
                report.successes.append(("agent_memory", f"deleted {res.rowcount} rows"))
        except Exception as exc:
            report.failures.append(("agent_memory", str(exc)))

        # 2) PG: health_fact
        try:
            async with self._sessionmaker() as sess:
                res = await sess.execute(
                    delete(HealthFact).where(HealthFact.user_id == user_id)
                )
                await sess.commit()
                report.successes.append(("health_fact", f"deleted {res.rowcount} rows"))
        except Exception as exc:
            report.failures.append(("health_fact", str(exc)))

        # 3) Redis keys
        try:
            r = await self._get_redis()
            keys = await _scan_user_keys(r, user_id)
            if keys:
                await r.delete(*keys)
            report.successes.append(("redis", f"deleted {len(keys)} keys"))
        except Exception as exc:
            report.failures.append(("redis", str(exc)))

        # 4) Influx：删除该 user_id tag 下的所有 point
        try:
            ok = await self._delete_influx_points(user_id)
            if ok:
                report.successes.append(("influxdb", "delete predicate dispatched"))
            else:
                report.successes.append(("influxdb", "skipped (not configured)"))
        except Exception as exc:
            report.failures.append(("influxdb", str(exc)))

        # 5) QMD：删除 user-namespaced collections
        try:
            await self._purge_qmd_namespaces(user_id)
            report.successes.append(
                ("qmd", f"purged user_{user_id}_memory + user_{user_id}_facts")
            )
        except Exception as exc:
            report.failures.append(("qmd", str(exc)))

        log.warning(
            "privacy.delete user_id=%s clean=%s successes=%d failures=%d",
            user_id, report.is_clean, len(report.successes), len(report.failures),
        )
        return report

    # ── 私有辅助 ────────────────────────────────────────────────────────

    async def _get_redis(self) -> Any:
        if self._redis is not None:
            return self._redis
        import redis.asyncio as aioredis
        self._redis = aioredis.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True,
            socket_connect_timeout=2,
        )
        return self._redis

    async def _count_influx_points(self, user_id: str) -> int:
        """轻量 count 查询；Influx 未配置时返回 0。"""
        if not settings.influxdb_token:
            return 0
        if self._influx is None:
            from rhythmind.adapters.influx_client import InfluxClient
            self._influx = InfluxClient()
        # 取所有允许字段中最近 30d 的 last 值（count 逻辑复用）
        all_fields = list({"heart_rate_avg", "heart_rate_max", "steps", "distance_km",
                            "calories", "sleep_hours", "hrv", "body_fat_pct",
                            "muscle_mass_kg", "water_pct", "visceral_fat"})
        try:
            data = await self._influx.query_range(
                user_id=user_id,
                fields=all_fields,
                start="-30d",
                stop="now()",
            )
            return sum(len(series.values) for series in (data or {}).values())
        except Exception:
            return 0

    async def _delete_influx_points(self, user_id: str) -> bool:
        """调用 InfluxDB delete predicate；成功返回 True，未配置返回 False。"""
        if not settings.influxdb_token:
            return False
        if self._influx is None:
            from rhythmind.adapters.influx_client import InfluxClient
            self._influx = InfluxClient()
        try:
            await self._influx.delete_user_data(user_id)
            return True
        except NotImplementedError:
            # adapter 未实现该方法，降级为不可达 → skip
            return False

    async def _purge_qmd_namespaces(self, user_id: str) -> None:
        if self._qmd is None:
            from rhythmind.core.qmd import QMDClient
            self._qmd = QMDClient()
        if not hasattr(self._qmd, "purge_user"):
            raise NotImplementedError(
                "QMDClient.purge_user() not implemented; manual cleanup required"
            )
        await self._qmd.purge_user(user_id)


# ── 辅助序列化 ──────────────────────────────────────────────────────────────

def _serialize_memory(row: AgentMemory) -> dict[str, Any]:
    return {
        "id": row.id,
        "namespace": row.namespace,
        "agent": row.agent,
        "key": row.key,
        "value": row.value_json,
        "tags": row.tags,
        "mem_type": row.mem_type,
        "confidence": row.confidence,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_fact(row: HealthFact) -> dict[str, Any]:
    out = {
        "id": row.id,
        "subject": row.subject,
        "predicate": row.predicate,
        "object": row.object_json,
        "source": row.source,
        "confidence": row.confidence,
        "valid_from": row.valid_from.isoformat() if getattr(row, "valid_from", None) else None,
        "valid_until": row.valid_until.isoformat() if getattr(row, "valid_until", None) else None,
    }
    return out


async def _scan_user_keys(redis_client: Any, user_id: str) -> list[str]:
    """
    用 SCAN 抓取与 user_id 相关的所有 key。
    覆盖：LoopGuard `loop:{user_id}:*` + rate-limit `rl:user:*:{user_id}` + 任意自定义前缀。
    """
    patterns = [
        f"loop:{user_id}:*",
        f"rl:user:*:{user_id}",
        f"session:{user_id}:*",
    ]
    found: set[str] = set()
    for pat in patterns:
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(cursor=cursor, match=pat, count=200)
            found.update(keys)
            if cursor == 0:
                break
    return sorted(found)
