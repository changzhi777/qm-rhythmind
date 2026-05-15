# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
adapters/influx_client.py — InfluxDB 异步客户端

职责：
  - 可穿戴设备指标的时序写入（write_metrics）
  - 按用户+时间窗口查询历史趋势（query_range）
  - 查询最近一条记录（query_latest）
  - 聚合统计（query_aggregated）

Schema 设计：
  measurement : health_metrics
  tags        : user_id, source, sport_type
  fields      : heart_rate_avg, heart_rate_max, steps, distance_km,
                calories, sleep_hours, hrv, body_fat_pct,
                muscle_mass_kg, water_pct, visceral_fat
  timestamp   : 记录时间（UTC，纳秒精度）

查询语言：Flux（InfluxDB 2.x）

依赖：influxdb-client[async]（已在 pyproject.toml 声明）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from rhythmind.config import settings

logger = logging.getLogger(__name__)

# InfluxDB 数值字段白名单（防止写入非法列）
_ALLOWED_FIELDS = frozenset({
    "heart_rate_avg", "heart_rate_max",
    "steps", "distance_km", "calories",
    "sleep_hours", "hrv",
    "body_fat_pct", "muscle_mass_kg", "water_pct", "visceral_fat",
})

# InfluxDB Tag 白名单
_ALLOWED_TAGS = frozenset({"user_id", "source", "sport_type"})


class InfluxUnavailableError(Exception):
    """InfluxDB 不可达（降级用）。"""


@dataclass
class MetricPoint:
    """
    单次健康数据写入点。

    tags   — 低基数维度（索引），用于 WHERE 过滤
    fields — 数值测量值，按需传入
    ts     — 记录时间戳（UTC），默认 now()
    """
    user_id: str
    source: str                           # garmin/apple/huawei/xiaomi/manual
    sport_type: str = "general"
    fields: dict[str, float | int] = field(default_factory=dict)
    ts: datetime | None = None

    def __post_init__(self) -> None:
        if self.ts is None:
            self.ts = datetime.now(tz=UTC)
        # 过滤非法 field
        self.fields = {
            k: v for k, v in self.fields.items()
            if k in _ALLOWED_FIELDS and v is not None
        }


@dataclass
class TrendSeries:
    """query_range() 返回的单指标时序数据。"""
    field: str
    values: list[tuple[datetime, float]]  # [(timestamp, value), ...]

    @property
    def latest(self) -> float | None:
        return self.values[-1][1] if self.values else None

    @property
    def oldest(self) -> float | None:
        return self.values[0][1] if self.values else None

    @property
    def avg(self) -> float | None:
        if not self.values:
            return None
        return sum(v for _, v in self.values) / len(self.values)

    @property
    def delta(self) -> float | None:
        """最新值 - 最旧值。"""
        if len(self.values) < 2:
            return None
        return round(self.latest - self.oldest, 2)  # type: ignore[operator]


class InfluxClient:
    """
    InfluxDB 2.x 异步客户端（懒初始化，应用启动时不建连接）。

    单例使用：在 MetricsAgent 中持有，跨请求复用连接。
    """

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        org: str | None = None,
        bucket: str | None = None,
    ) -> None:
        self._url = url or settings.influxdb_url
        self._token = token or settings.influxdb_token
        self._org = org or settings.influxdb_org
        self._bucket = bucket or settings.influxdb_bucket
        self._client: Any = None  # influxdb_client.InfluxDBClientAsync

    def _get_client(self) -> Any:
        """懒初始化：首次调用时建立连接。"""
        if self._client is None:
            try:
                from influxdb_client.client.influxdb_client_async import (
                    InfluxDBClientAsync,
                )
                self._client = InfluxDBClientAsync(
                    url=self._url,
                    token=self._token,
                    org=self._org,
                    timeout=10_000,  # ms
                )
            except ImportError as e:
                raise InfluxUnavailableError(
                    "influxdb-client[async] not installed"
                ) from e
        return self._client

    # ── 写入 ──────────────────────────────────────────────────────────────

    async def write_metrics(self, point: MetricPoint | list[MetricPoint]) -> bool:
        """
        写入单条或批量健康数据。

        Args:
            point: 单条 MetricPoint 或 list[MetricPoint]（批量写入）

        Returns:
            True 全部成功，False 有失败（部分成功也返回 False）
        """
        points = [point] if isinstance(point, MetricPoint) else point
        if not points:
            return True

        all_ok = True
        for p in points:
            if not p.fields:
                logger.debug("influx.write skip: no valid fields for user=%s", p.user_id)
                continue

            try:
                from influxdb_client.client.write.point import Point as InfluxPoint
                from influxdb_client.domain.write_precision import WritePrecision

                influx_pt = (
                    InfluxPoint("health_metrics")
                    .tag("user_id", p.user_id)
                    .tag("source", p.source)
                    .tag("sport_type", p.sport_type)
                    .time(p.ts, WritePrecision.S)
                )
                for k, v in p.fields.items():
                    influx_pt = influx_pt.field(k, float(v))

                async with self._get_client() as client:
                    write_api = client.write_api()
                    await write_api.write(bucket=self._bucket, record=influx_pt)

                logger.info(
                    "influx.write ok user=%s source=%s fields=%s",
                    p.user_id, p.source, list(p.fields.keys()),
                )
            except InfluxUnavailableError:
                raise
            except Exception as e:
                logger.error("influx.write error: %s", e)
                all_ok = False

        return all_ok

    # ── 查询 ──────────────────────────────────────────────────────────────

    async def query_range(
        self,
        user_id: str,
        fields: list[str],
        start: str = "-7d",
        stop: str = "now()",
        aggregation_window: str = "1d",
        fn: str = "mean",
    ) -> dict[str, TrendSeries]:
        """
        查询指定时间范围内的指标趋势。

        Args:
            user_id:             用户 ID
            fields:              要查询的字段列表
            start:               起始时间（Flux 相对时间，如 "-7d"）
            stop:                结束时间
            aggregation_window:  聚合窗口（"1d" = 每天一个点）
            fn:                  聚合函数（mean/max/min/last）

        Returns:
            {field_name: TrendSeries}
        """
        # 过滤非法 field，防 Flux 注入
        safe_fields = [f for f in fields if f in _ALLOWED_FIELDS]
        if not safe_fields:
            return {}

        # 生成 Flux 查询（每个 field 一个子查询，union 合并）
        field_filters = " or ".join(
            f'r._field == "{f}"' for f in safe_fields
        )
        flux = f"""
from(bucket: "{self._bucket}")
  |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => r._measurement == "health_metrics")
  |> filter(fn: (r) => r.user_id == "{user_id}")
  |> filter(fn: (r) => {field_filters})
  |> aggregateWindow(every: {aggregation_window}, fn: {fn}, createEmpty: false)
  |> sort(columns: ["_time"], desc: false)
"""
        try:
            async with self._get_client() as client:
                query_api = client.query_api()
                tables = await query_api.query(flux)

            result: dict[str, TrendSeries] = {}
            for table in tables:
                for record in table.records:
                    fname = record.get_field()
                    ts = record.get_time()
                    val = record.get_value()
                    if fname not in result:
                        result[fname] = TrendSeries(field=fname, values=[])
                    result[fname].values.append((ts, float(val)))

            logger.debug(
                "influx.query_range user=%s fields=%s start=%s rows=%d",
                user_id, safe_fields, start, sum(len(s.values) for s in result.values()),
            )
            return result

        except InfluxUnavailableError:
            raise
        except Exception as e:
            logger.error("influx.query_range error: %s", e)
            return {}

    async def query_latest(
        self,
        user_id: str,
        fields: list[str],
    ) -> dict[str, float]:
        """
        查询各指标最近一条记录（用于基线对比）。

        Returns:
            {field_name: latest_value}
        """
        safe_fields = [f for f in fields if f in _ALLOWED_FIELDS]
        if not safe_fields:
            return {}

        field_filters = " or ".join(
            f'r._field == "{f}"' for f in safe_fields
        )
        flux = f"""
from(bucket: "{self._bucket}")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "health_metrics")
  |> filter(fn: (r) => r.user_id == "{user_id}")
  |> filter(fn: (r) => {field_filters})
  |> last()
"""
        try:
            async with self._get_client() as client:
                query_api = client.query_api()
                tables = await query_api.query(flux)

            result: dict[str, float] = {}
            for table in tables:
                for record in table.records:
                    result[record.get_field()] = float(record.get_value())
            return result

        except Exception as e:
            logger.error("influx.query_latest error: %s", e)
            return {}

    async def delete_user_data(self, user_id: str) -> bool:
        """
        删除指定用户的所有时序数据（GDPR/PIPL 删除权实现）。

        使用 InfluxDB DeletePredicate API，按 user_id tag 过滤删除。
        注意：InfluxDB 删除是软删除（mark-and-sweep），实际删除发生在 TSM compaction 阶段。

        Args:
            user_id: 用户 ID

        Returns:
            True 删除请求成功提交，False 失败（不抛出异常）。
        """
        try:
            async with self._get_client() as client:
                delete_api = client.delete_api()
                # 删除条件：user_id tag 等于目标用户
                predicate = f'user_id="{user_id}"'
                # 时间范围：全部（从 epoch 到未来）
                start = "1970-01-01T00:00:00Z"
                stop = "2100-01-01T00:00:00Z"
                await delete_api.delete(
                    start=start,
                    stop=stop,
                    predicate=predicate,
                    bucket=self._bucket,
                    org=self._org,
                )
            logger.info("influx.delete_user_data ok user_id=%s", user_id)
            return True

        except InfluxUnavailableError:
            raise
        except Exception as e:
            logger.error("influx.delete_user_data error user_id=%s: %s", user_id, e)
            return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
