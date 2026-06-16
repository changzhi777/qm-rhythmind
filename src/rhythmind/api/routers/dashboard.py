"""
api/routers/dashboard.py — 仪表盘 + 多模态上传 + Chat 代理 API 端点

端点：
  GET  /qm/api/dashboard             — 仪表盘汇总数据（Redis 缓存 30s）
  GET  /qm/api/influxdb/timeseries   — InfluxDB 时序数据查询（白名单字段）
  POST /qm/api/analyze               — 触发本地模型重新分析
  POST /qm/api/import-facts          — 批量导入健康事实数据
  POST /qm/api/upload/file           — 通用文件上传
                                          （CSV/JSON/TXT/PDF/图像，多模态 AI 分析）
  POST /qm/api/chat                  — Chat 代理（转发到 HealthRouter）

注：报告相关端点（/reports、/test-reports）已迁移至 `reports.py`
   用户摘要端点（/users/summary）已迁移至 `users_summary.py`
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, cast

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException

from rhythmind.api.deps import CurrentUserId
from rhythmind.api.routers._common import _fm
from rhythmind.config import settings
from rhythmind.core.memory.fact_manager import FactManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/qm/api", tags=["dashboard"])


_dashboard_redis: aioredis.Redis | None = None


def _get_dashboard_redis() -> aioredis.Redis | None:
    try:
        global _dashboard_redis
        if _dashboard_redis is None:
            _dashboard_redis = aioredis.from_url(  # type: ignore[no-untyped-call]
                settings.redis_url, encoding="utf-8", decode_responses=True
            )
        return _dashboard_redis
    except Exception:
        return None


# ── InfluxDB 时序端点 ──────────────────────────────────────────────
# 允许前端查询的 InfluxDB 字段白名单（与 adapters/influx_client._ALLOWED_FIELDS 同步）
_INFLUX_METRIC_WHITELIST = frozenset({
    "heart_rate_avg", "heart_rate_max",
    "steps", "distance_km", "calories",
    "sleep_hours", "hrv",
    "body_fat_pct", "muscle_mass_kg", "water_pct", "visceral_fat",
})
# 允许的 aggregation 窗口
_INFLUX_AGG_WHITELIST = frozenset({"1h", "1d", "1w"})


@router.get("/influxdb/timeseries")
async def get_influx_timeseries(
    user_id: CurrentUserId,
    metric: str,
    range: str = "-7d",
    aggregation: str = "1d",
    fn: str = "mean",
) -> dict[str, Any]:
    """
    查询指定用户的 InfluxDB 时序数据。

    Query:
      metric      - 必填，白名单内字段（如 heart_rate_avg）
      range       - Flux 相对时间，默认 "-7d"（7天）
      aggregation - 聚合窗口，默认 "1d"（每天一个点）
      fn          - 聚合函数 mean/max/min/last，默认 mean

    Returns:
      {
        "status": "ok",
        "metric": "heart_rate_avg",
        "range": "-7d",
        "aggregation": "1d",
        "data": [{"ts": "2026-06-04T00:00:00Z", "value": 72.5}, ...],
        "count": 7,
        "latest": 72.5,
      }
    """
    # 1. 参数白名单校验（防 Flux 注入）
    if metric not in _INFLUX_METRIC_WHITELIST:
        allowed = sorted(_INFLUX_METRIC_WHITELIST)
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 metric: {metric}。允许: {allowed}",
        )
    if aggregation not in _INFLUX_AGG_WHITELIST:
        allowed_agg = sorted(_INFLUX_AGG_WHITELIST)
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 aggregation: {aggregation}。允许: {allowed_agg}",
        )
    if fn not in {"mean", "max", "min", "last"}:
        raise HTTPException(status_code=400, detail=f"不支持的 fn: {fn}")

    # 2. range 格式校验：必须以 - 开头（相对时间）
    if not range.startswith("-"):
        raise HTTPException(
            status_code=400,
            detail=f"range 格式错误（必须以 '-' 开头，如 '-7d'）: {range}",
        )

    try:
        from rhythmind.adapters.influx_client import InfluxClient
        client = InfluxClient()
        series_map = await client.query_range(
            user_id=user_id,
            fields=[metric],
            start=range,
            stop="now()",
            aggregation_window=aggregation,
            fn=fn,
        )
    except Exception as exc:
        logger.warning("influxdb.timeseries query failed user=%s metric=%s: %s",
                       user_id, metric, exc)
        return {
            "status": "degraded",
            "metric": metric,
            "range": range,
            "aggregation": aggregation,
            "data": [],
            "count": 0,
            "latest": None,
            "error": "InfluxDB 不可达，请稍后重试",
        }

    # 3. 转换为前端友好的格式
    series = series_map.get(metric)
    data_points: list[dict[str, Any]] = []
    if series and series.values:
        for ts, value in series.values:
            data_points.append({
                "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "value": round(value, 2),
            })

    return {
        "status": "ok",
        "metric": metric,
        "range": range,
        "aggregation": aggregation,
        "fn": fn,
        "data": data_points,
        "count": len(data_points),
        "latest": series.latest if series else None,
        "avg": series.avg if series else None,
    }


@router.get("/dashboard")
async def get_dashboard(user_id: CurrentUserId) -> dict[str, Any]:
    """返回仪表盘汇总数据（Redis 缓存 30s）。"""
    cache = _get_dashboard_redis()
    if cache:
        try:
            cached = await cache.get(f"dashboard:{user_id}")
            if cached:
                import json as _json
                return cast(dict[str, Any], _json.loads(cached))
        except Exception:
            pass

    fm = _fm(user_id)
    facts = await fm.get_all_current()
    data: dict[str, Any] = {}
    for f in facts:
        data[f"{f.subject}.{f.predicate}"] = f.object_json
    result = {"status": "ok", "data": data}

    if cache:
        try:
            await cache.setex(
                f"dashboard:{user_id}", 30, json.dumps(result, ensure_ascii=False)
            )
        except Exception:
            pass

    return result


@router.post("/analyze")
async def trigger_analysis(user_id: CurrentUserId) -> dict[str, Any]:
    """触发本地模型重新分析。"""
    from rhythmind.adapters.adapter_router import adapter_router
    from rhythmind.config import settings

    fm = _fm(user_id)
    facts = await fm.get_all_current()
    if not facts:
        raise HTTPException(
            status_code=400,
            detail="无数据，请先执行入库 (python scripts/run_ingestion.py)",
        )

    import json
    from datetime import UTC

    fact_summary = []
    for f in facts:
        fact_summary.append(
            f"- [{f.subject}/{f.predicate}]: "
            f"{json.dumps(f.object_json, ensure_ascii=False)}"
        )

    system_prompt = (
        "你是一位专业的运动健康 AI 分析师。"
        "根据用户的健康数据事实，生成一份专业的中文分析报告。"
        "\n\n"
        "报告格式要求（Markdown）：\n"
        "1. **总体评价**（1-2段）\n"
        "2. **运动能力评估**（VO2Max、耐力、配速分析）\n"
        "3. **健康风险评估**（心率、HRV、睡眠）\n"
        "4. **训练负荷分析**（急性/慢性负荷比）\n"
        "5. **赛事能力预测**（基于当前数据）\n"
        "6. **个性化建议**（3-5条具体可执行的建议）\n"
        "\n"
        "注意：\n"
        "- 所有分析基于事实数据，不做无依据推测\n"
        "- 如果某项数据异常，指出具体问题和建议\n"
        "- 语言专业但不晦涩，适合运动爱好者阅读\n"
        "- 报告长度控制在 800-1200 字"
    )

    user_prompt = f"""以下是用户的健康数据事实：

{chr(10).join(fact_summary)}

请基于以上数据生成专业健康分析报告。"""

    model_spec = settings.model_compliance_spec or "omlX://gemma-4-e4b-it-4bit"
    logger.info("triggering AI analysis with model: %s", model_spec)

    # 使用长超时直接创建适配器（报告生成耗时长）
    if model_spec.startswith("omlX://"):
        from rhythmind.adapters.omlX_adapter import OMLXAdapter
        model_name = model_spec[len("omlX://"):]
        analysis_adapter = OMLXAdapter(model_name, timeout=120.0)
        report_content = await analysis_adapter.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_tokens=4096,
        )
    else:
        report_content = await adapter_router.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model_spec=model_spec,
            temperature=0.4,
            max_tokens=4096,
        )

    await fm.write_fact("ai_report", "analysis", {
        "content": report_content,
        "model": model_spec,
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }, source="ai_analysis")

    return {"status": "ok", "message": "分析完成", "chars": len(report_content)}


@router.post("/import-facts")
async def import_facts(
    user_id: CurrentUserId,
    facts: list[dict[str, Any]],
) -> dict[str, Any]:
    """批量导入健康事实数据（管理端点，供数据迁移使用）。

    请求体格式：
    [
      {
          "subject": "profile",
          "predicate": "gender",
          "object_json": "MALE",
          "source": "garmin",
      },
      {
          "subject": "profile",
          "predicate": "vo2_max",
          "object_json": 52.0,
          "source": "garmin",
      },
      ...
    ]
    """
    if not isinstance(facts, list):
        raise HTTPException(status_code=400, detail="请求体必须是数组")

    fm = _fm(user_id)
    imported = 0
    errors: list[str] = []

    for i, item in enumerate(facts):
        subject = item.get("subject")
        predicate = item.get("predicate")
        object_json = item.get("object_json")
        source = item.get("source", "import")

        if not subject or not predicate:
            errors.append(f"第 {i} 条缺少 subject 或 predicate")
            continue

        try:
            await fm.write_fact(subject, predicate, object_json, source=source)
            imported += 1
        except Exception as exc:
            errors.append(f"第 {i} 条写入失败: {exc}")

    logger.info(
        "import_facts user=%s imported=%d errors=%d",
        user_id, imported, len(errors),
    )

    return {
        "status": "ok",
        "imported": imported,
        "errors": errors,
    }


# ── 文件上传 + Chat 代理 ───────────────────────────────────

import base64
import contextlib
import csv
import io as _io

from fastapi import File, UploadFile


def _pdf_to_images_b64(pdf_bytes: bytes, dpi: int = 150) -> list[dict[str, str]]:
    """将 PDF 每页转为 base64 编码的 PNG 图片。"""
    try:
        from pdf2image import convert_from_bytes  # type: ignore[import-not-found]
    except ImportError:
        raise RuntimeError(
            "pdf2image 未安装，请执行: pip install pdf2image && brew install poppler"
        ) from None

    images = convert_from_bytes(pdf_bytes, dpi=dpi)
    result = []
    for img in images[:5]:  # 最多处理前 5 页
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        result.append({"b64": b64, "mime": "image/png"})
    return result


async def _analyze_with_vision(
    images: list[dict[str, str]],
    prompt: str,
) -> dict[str, Any]:
    """用多模态模型分析图片，返回结构化 JSON。"""
    from rhythmind.adapters.adapter_router import adapter_router
    from rhythmind.config import settings

    content_parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for img in images:
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{img['mime']};base64,{img['b64']}"},
        })

    messages = [
        {
            "role": "system",
            "content": "你是专业的健康数据分析助手，擅长从医学报告和健康数据图片中提取结构化数据。只返回纯 JSON。",  # noqa: E501
        },
        {"role": "user", "content": content_parts},
    ]

    model_spec = settings.model_compliance_spec or "omlX://gemma-4-e4b-it-4bit"
    logger.info("vision analysis with model=%s images=%d", model_spec, len(images))

    if model_spec.startswith("omlX://"):
        from rhythmind.adapters.omlX_adapter import OMLXAdapter
        adapter: Any = OMLXAdapter(model_spec[len("omlX://"):], timeout=120.0)
    else:
        adapter = adapter_router.get(model_spec)

    raw = await adapter.chat(
        cast(list[dict[str, Any]], messages),
        temperature=0.1, max_tokens=4096,
    )

    # 清理 markdown 包裹的 JSON
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()

    try:
        return cast(dict[str, Any], json.loads(raw))
    except json.JSONDecodeError:
        return {"raw_text": raw}


async def _write_vision_facts(
    fm: FactManager, subject_prefix: str, data: dict[str, Any], filename: str,
) -> int:
    """将 AI 提取的结构化数据写入 FactManager，展开嵌套结构。"""
    _SOURCE = "vision_analysis"  # noqa: N806 — 模块内常量

    async def _write(predicate: str, obj: Any) -> None:
        await fm.write_fact(subject_prefix, predicate, obj, source=_SOURCE)

    count = 0
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (str, int, float, bool)):
                await _write(key, value)
                count += 1
            elif isinstance(value, dict):
                # 展开嵌套 dict
                for sub_key, sub_val in value.items():
                    await _write(f"{key}.{sub_key}", sub_val)
                    count += 1
            elif isinstance(value, list):
                # 展开数组中的每个 dict 元素
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        # 用 test_name/name 等字段作为键
                        item_key = (
                            item.get("test_name")
                            or item.get("name")
                            or item.get("指标")
                            or str(i)
                        )
                        await _write(f"{key}.{item_key}", item)
                        count += 1
                    elif isinstance(item, (str, int, float)):
                        await _write(f"{key}.{i}", item)
                        count += 1
                if not value:
                    await _write(key, {"items": value})
                    count += 1

    await _write(
        "_source",
        {"filename": filename, "extracted": count},
    )
    return max(count, 1)


@router.post("/upload/file")
async def upload_file(
    file: UploadFile = File(...),
    user_id: CurrentUserId | None = None,
) -> dict[str, Any]:
    """通用文件上传端点 — 自动识别类型并解析入库。

    支持: CSV, JSON, TXT, PDF(文本提取), 图像(OCR 占位)
    """
    if user_id is None:
        user_id = "garmin_user_001"

    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    content = await file.read()

    fm = _fm(user_id)
    facts_imported = 0
    summary = ""

    if ext == "csv":
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(_io.StringIO(text))
        rows = list(reader)
        if not rows:
            return {"status": "ok", "message": "CSV 为空", "facts_imported": 0}

        cols = list(rows[0].keys())
        for row in rows:
            for col in cols:
                val = row[col].strip()
                if val:
                    with contextlib.suppress(ValueError):
                        val = float(val) if "." in val else int(val)
                    await fm.write_fact(
                        "upload_csv", f"{col}", val, source="file_upload"
                    )
                    facts_imported += 1
        summary = f"CSV {len(rows)} 行 × {len(cols)} 列，导入 {facts_imported} 条数据"

    elif ext == "json":
        data = json.loads(content)
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (str, int, float, bool, dict)):
                    await fm.write_fact("upload_json", key, value, source="file_upload")
                    facts_imported += 1
            summary = f"JSON 对象，导入 {facts_imported} 个字段"
        elif isinstance(data, list):
            facts_imported = len(data)
            await fm.write_fact(
                "upload_json", "array_data", {"count": len(data)}, source="file_upload"
            )
            summary = f"JSON 数组，{len(data)} 条记录"
        else:
            return {
                "status": "ok",
                "message": "不支持的 JSON 格式",
                "facts_imported": 0,
            }

    elif ext == "txt":
        text = content.decode("utf-8", errors="replace")
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        await fm.write_fact(
            "upload_text",
            "content",
            {"lines": len(lines), "preview": text[:500]},
            source="file_upload",
        )
        facts_imported = 1
        summary = f"文本文件，{len(lines)} 行"

    elif ext == "pdf":
        try:
            images_b64 = _pdf_to_images_b64(content)
            ai_result = await _analyze_with_vision(
                images_b64,
                "这是一份医学/健康 PDF 报告。请提取其中所有健康相关数据（如血液指标、身高体重、心率、血压、血糖、血脂等），以 JSON 格式返回。只返回 JSON，不要其他文字。",  # noqa: E501
            )
            facts_imported = await _write_vision_facts(
                fm, "pdf_report", ai_result, filename
            )
            summary = f"PDF 多模态分析完成，提取 {facts_imported} 条数据"
        except Exception as e:
            logger.warning("PDF vision analysis failed, fallback: %s", e)
            await fm.write_fact(
                "upload_file",
                "pdf_received",
                {"filename": filename, "size": len(content)},
                source="file_upload",
            )
            facts_imported = 1
            summary = f"PDF 已接收（AI 分析暂不可用: {str(e)[:60]}）"

    elif ext in ("png", "jpg", "jpeg"):
        try:
            import base64
            img_b64 = base64.b64encode(content).decode("utf-8")
            mime = f"image/{'jpeg' if ext in ('jpg','jpeg') else ext}"
            ai_result = await _analyze_with_vision(
                [{"b64": img_b64, "mime": mime}],
                "这是一张健康/医学相关的图片（如化验单、体检报告、体脂秤读数等）。请提取其中所有健康数据，以 JSON 格式返回。只返回 JSON，不要其他文字。",  # noqa: E501
            )
            facts_imported = await _write_vision_facts(
                fm, "image_report", ai_result, filename
            )
            summary = f"图像多模态分析完成，提取 {facts_imported} 条数据"
        except Exception as e:
            logger.warning("Image vision analysis failed, fallback: %s", e)
            await fm.write_fact(
                "upload_file",
                "image_received",
                {"filename": filename, "size": len(content), "type": ext},
                source="file_upload",
            )
            facts_imported = 1
            summary = f"图像已接收（AI 分析暂不可用: {str(e)[:60]}）"

    else:
        return {
            "status": "error",
            "message": f"不支持的文件格式: .{ext}",
            "facts_imported": 0,
        }

    logger.info(
        "upload_file user=%s file=%s facts=%d", user_id, filename, facts_imported
    )
    return {
        "status": "ok",
        "message": f"{filename} 上传成功",
        "filename": filename,
        "facts_imported": facts_imported,
        "summary": summary,
    }


@router.post("/chat")
async def chat_proxy(
    body: dict[str, Any],
    user_id: CurrentUserId | None = None,
) -> dict[str, Any]:
    """Chat 代理端点 — 将前端请求转发到后端 HealthRouter。

    请求体: { "text": "...", "context": {} }
    """
    if user_id is None:
        user_id = "garmin_user_001"

    text = body.get("text", "")
    context = body.get("context", {})

    if not text.strip():
        return {"status": "ok", "message": "请输入消息"}

    try:
        from rhythmind.api.deps import get_router
        health_router = get_router()
        import uuid

        session_id = str(uuid.uuid4())
        raw_input = {"text": text, **context}
        result = await health_router.route(
            user_id=user_id,
            raw_input=raw_input,
            session_id=session_id,
        )

        return {
            "status": (
                result.status.value
                if hasattr(result.status, "value")
                else str(result.status)
            ),
            "session_id": session_id,
            "message": result.message,
            "data": result.data,
        }
    except Exception as exc:
        logger.warning("chat_proxy fallback: %s", exc)
        fm = _fm(user_id)
        facts = await fm.get_all_current()
        if not facts:
            return {
                "status": "ok",
                "message": "暂无健康数据，请先上传数据文件。",
                "data": {
                    "coach_response": "暂无健康数据，请先通过上传页面导入数据文件，我才能为你提供健康分析。",  # noqa: E501
                },
            }

        fact_lines = [
            f"- [{f.subject}/{f.predicate}]: "
            f"{json.dumps(f.object_json, ensure_ascii=False)}"
            for f in facts[:20]
        ]
        return {
            "status": "ok",
            "message": "数据摘要",
            "data": {
                "coach_response": (
                    f"当前已录入 {len(facts)} 条健康数据：\n" + "\n".join(fact_lines)
                ),
            },
        }

