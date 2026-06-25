# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
api/routers/analyze_with_source.py — 一体化"再报告"端点 (2026-06-25)

端点：
  POST /qm/api/analyze/with-source

背景:
  原 /analyze 端点只触发 LLM 分析,要求 fact_manager 中已有数据。
  用户若要换数据源(预置目录/上传/URL),需手动跑 Python 脚本或多次点击。

功能:
  一链点动完成"选择数据源 → 入库 → 触发 LLM 分析 → 返回报告"。
  3 种数据源:
    - 预置目录(garmin_20260526): 扫描仓库内 佳明数据20260526/ 目录
    - 文件上传(upload): multipart/form-data files
    - URL 拉取(url): httpx 拉取后入库

响应:
  { status, source, ingested: {facts_imported, message}, report: {id, content, model, timestamp} }
"""
from __future__ import annotations

import contextlib
import csv
import io as _io
import json
import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from rhythmind.api.deps import CurrentUserId
from rhythmind.api.routers._common import _fm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/qm/api", tags=["analyze"])


# ── Source 枚举 ───────────────────────────────────────────────────────────


class SourceType(str, Enum):
    """支持的数据源类型。"""

    GARMIN_20260526 = "garmin_20260526"  # 预置佳明 20260526 完整数据
    UPLOAD = "upload"  # 用户上传文件
    URL = "url"  # 远程 URL 拉取


# ── 上传文件解析 (从 /upload/file 抽取) ─────────────────────────────────


async def _parse_uploaded_file(fm, file: UploadFile) -> dict[str, Any]:
    """解析单文件并写入 fact_manager。

    支持: CSV, JSON, TXT, PDF(简化为存元数据), 图像(简化为存元数据)
    返回: { facts_imported, message, summary }
    """
    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    content = await file.read()

    facts_imported = 0
    summary = ""

    if ext == "csv":
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(_io.StringIO(text))
        rows = list(reader)
        if not rows:
            return {"facts_imported": 0, "message": "CSV 为空", "summary": "CSV 空文件"}
        cols = list(rows[0].keys())
        for row in rows:
            for col in cols:
                val = row[col].strip()
                if val:
                    with contextlib.suppress(ValueError):
                        val = float(val) if "." in val else int(val)
                    await fm.write_fact("upload_csv", f"{col}", val, source="with_source")
                    facts_imported += 1
        summary = f"CSV {len(rows)} 行 × {len(cols)} 列"

    elif ext == "json":
        data = json.loads(content)
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (str, int, float, bool, dict)):
                    await fm.write_fact("upload_json", key, value, source="with_source")
                    facts_imported += 1
            summary = f"JSON 对象，{facts_imported} 字段"
        elif isinstance(data, list):
            await fm.write_fact("upload_json", "array_data", {"count": len(data)}, source="with_source")
            facts_imported = 1
            summary = f"JSON 数组，{len(data)} 条"
        else:
            return {"facts_imported": 0, "message": "不支持的 JSON 格式", "summary": ""}

    elif ext == "txt":
        text = content.decode("utf-8", errors="replace")
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        await fm.write_fact(
            "upload_text",
            "content",
            {"lines": len(lines), "preview": text[:500]},
            source="with_source",
        )
        facts_imported = 1
        summary = f"文本 {len(lines)} 行"

    else:
        # 不支持类型: 仅存元数据
        await fm.write_fact(
            "upload_file",
            ext or "unknown",
            {"filename": filename, "size": len(content)},
            source="with_source",
        )
        facts_imported = 1
        summary = f"已存 .{ext} 元数据"

    return {"facts_imported": facts_imported, "message": f"{filename} 处理完成", "summary": summary}


# ── 预置数据源导入 ─────────────────────────────────────────────────────


async def _ingest_garmin_20260526(fm) -> dict[str, Any]:
    """扫描 佳明数据20260526/ 目录,生成 30+ 条健康事实。"""
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[4]  # /qm-rhythmind/qm-rhythmind
    sys.path.insert(0, str(repo_root / "scripts"))
    scripts_dir = repo_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    try:
        from load_garmin_20260526 import build_dataset, persona_from_dataset
    except ImportError as e:
        logger.error("import load_garmin_20260526 failed: %s", e)
        return {"facts_imported": 0, "message": f"无法加载预置数据脚本: {e}", "summary": ""}

    data_root = repo_root.parent / "佳明数据20260526"
    if not data_root.exists():
        return {"facts_imported": 0, "message": f"预置目录不存在: {data_root}", "summary": ""}

    ds = build_dataset(data_root)
    persona = persona_from_dataset(ds)
    facts_imported = 0

    # profile
    for key, value in ds.profile.items():
        if value is not None:
            await fm.write_fact("profile", key, value, source="garmin_20260526")
            facts_imported += 1

    # training
    for key, value in ds.training.items():
        await fm.write_fact("training", key, value, source="garmin_20260526")
        facts_imported += 1

    # sleep
    for key, value in ds.sleep.items():
        await fm.write_fact("sleep", key, value, source="garmin_20260526")
        facts_imported += 1

    # running
    for key, value in ds.running.items():
        await fm.write_fact("running", key, value, source="garmin_20260526")
        facts_imported += 1

    # activity_summary.yearly (字段实际是 yearly_activity)
    await fm.write_fact(
        "activity_summary", "yearly", ds.yearly_activity, source="garmin_20260526"
    )
    facts_imported += 1

    # fitness_age_history
    await fm.write_fact(
        "fitness_age", "history", ds.fitness_age_history, source="garmin_20260526"
    )
    facts_imported += 1

    # personal_records
    await fm.write_fact(
        "personal_records", "all", {"records": ds.personal_records}, source="garmin_20260526"
    )
    facts_imported += 1

    # lactate_threshold
    await fm.write_fact(
        "performance", "lactate_threshold", ds.lactate_threshold, source="garmin_20260526"
    )
    facts_imported += 1

    # trends
    for key, value in ds.trends.items():
        await fm.write_fact("trends", key, value, source="garmin_20260526")
        facts_imported += 1

    # user_profile persona
    await fm.write_fact("user_profile", "persona", persona, source="garmin_20260526")
    facts_imported += 1

    return {
        "facts_imported": facts_imported,
        "message": f"已从 {data_root.name}/ 导入 {facts_imported} 条事实",
        "summary": f"预置数据源 30+ 条",
    }


# ── URL 拉取 ─────────────────────────────────────────────────────────────


async def _ingest_url(fm, url: str) -> dict[str, Any]:
    """通过 HTTP 拉取 URL,按 content-type 解析入库。"""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content = resp.content
            ctype = resp.headers.get("content-type", "").lower()
    except Exception as e:
        return {"facts_imported": 0, "message": f"URL 拉取失败: {e}", "summary": ""}

    # 按 content-type 决定存储
    if "json" in ctype:
        try:
            data = resp.json()
            await fm.write_fact("url_source", "json_data", data, source="url")
        except Exception as e:
            return {"facts_imported": 0, "message": f"JSON 解析失败: {e}", "summary": ""}
        return {"facts_imported": 1, "message": f"URL JSON 入库成功", "summary": url}
    else:
        text = content.decode("utf-8", errors="replace")
        await fm.write_fact("url_source", "text_data", {
            "url": url, "size": len(content), "preview": text[:500]
        }, source="url")
        return {"facts_imported": 1, "message": f"URL 文本入库成功", "summary": url}


# ── LLM 分析 (复用 dashboard._do_analyze 逻辑) ─────────────────────────


async def _run_llm_analyze(user_id: str) -> dict[str, Any]:
    """调 oMLX 生成 AI 健康报告,返回 {id, content, model, timestamp}。"""
    from rhythmind.adapters.adapter_router import adapter_router
    from rhythmind.config import settings

    fm = _fm(user_id)
    facts = await fm.get_all_current()
    if not facts:
        raise HTTPException(status_code=400, detail="无数据，请先上传或选择数据源")

    KEY_FACTS = {
        ("profile", "age"), ("profile", "gender"), ("profile", "bmi"),
        ("profile", "vo2_max"), ("profile", "resting_hr"),
        ("training", "metrics"), ("sleep", "summary"),
        ("running", "summary"), ("activity_summary", "yearly"),
    }

    fact_summary = []
    for f in facts:
        if (f.subject, f.predicate) not in KEY_FACTS:
            continue
        obj_str = json.dumps(f.object_json, ensure_ascii=False)
        if len(obj_str) > 200:
            obj_str = obj_str[:200] + "..."
        fact_summary.append(f"- {f.subject}.{f.predicate}: {obj_str}")

    if not fact_summary:
        fact_summary = ["(无关键事实,基于通用分析)"]

    system_prompt = (
        "你是一位专业的运动健康 AI 分析师。"
        "根据用户的健康数据事实,生成一份专业的中文分析报告。\n\n"
        "报告格式要求(Markdown):\n"
        "1. **总体评价**(1-2 句话)\n"
        "2. **运动能力评估**(VO2Max、耐力、配速)\n"
        "3. **健康风险**(心率、睡眠)\n"
        "4. **训练建议**(3 条具体可执行)\n\n"
        "注意:\n"
        "- 报告长度控制在 500-800 字\n"
        "- 直接给结论和建议,不要重复事实"
    )

    user_prompt = "用户健康数据事实:\n" + "\n".join(fact_summary)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        report_content = await adapter_router.chat(
            messages=messages,
            model_spec=settings.model_primary_spec,
            temperature=0.3,
            max_tokens=1500,
        )
    except Exception as e:
        logger.exception("with_source LLM analyze failed: %s", e)
        raise HTTPException(status_code=500, detail=f"LLM 分析失败: {e}")

    # 写回 ai_report fact
    timestamp = datetime.now(tz=UTC).isoformat()
    fact = await fm.write_fact(
        "ai_report", "analysis",
        {
            "content": report_content,
            "model": settings.model_primary_spec,
            "timestamp": timestamp,
            "source": "with_source",
        },
        source="with_source_analyze",
    )

    return {
        "id": fact.id,
        "content": report_content,
        "model": settings.model_primary_spec,
        "timestamp": timestamp,
    }


# ── 端点 ────────────────────────────────────────────────────────────────


@router.post(
    "/analyze/with-source",
    summary="一链点动: 数据源入库 + LLM 重新分析",
    description="""
支持 3 种数据源:
  - garmin_20260526: 预置佳明 20260526 完整数据(无需参数)
  - upload: 接收 files[] (multipart/form-data)
  - url: 接收 url 字段,httpx 拉取后入库

流程:
  1. 鉴权 → 拿到 user_id
  2. 根据 source 分支入库
  3. 调 LLM 生成报告
  4. 写回 ai_report fact_manager
  5. 返回 {ingested, report}
""",
)
async def analyze_with_source(
    user_id: CurrentUserId,
    source: str = Form(..., description="garmin_20260526 | upload | url"),
    url: str = Form("", description="source=url 时必填"),
    files: list[UploadFile] = File(default_factory=list, description="source=upload 时必填"),
) -> dict[str, Any]:
    """一链点动: 数据源入库 + 触发 LLM 重新分析。"""
    try:
        source_enum = SourceType(source)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 source: {source},可选: {[s.value for s in SourceType]}",
        )

    fm = _fm(user_id)

    # 步骤 1: 入库
    if source_enum == SourceType.GARMIN_20260526:
        ingested = await _ingest_garmin_20260526(fm)
    elif source_enum == SourceType.UPLOAD:
        if not files:
            raise HTTPException(status_code=400, detail="source=upload 时 files 必填")
        total = {"facts_imported": 0, "message": "", "summary": ""}
        for f in files:
            r = await _parse_uploaded_file(fm, f)
            total["facts_imported"] += r["facts_imported"]
        total["message"] = f"已处理 {len(files)} 个文件"
        total["summary"] = f"{len(files)} files / {total['facts_imported']} facts"
        ingested = total
    elif source_enum == SourceType.URL:
        if not url:
            raise HTTPException(status_code=400, detail="source=url 时 url 必填")
        ingested = await _ingest_url(fm, url)
    else:
        raise HTTPException(status_code=400, detail=f"未实现: {source}")

    if ingested["facts_imported"] == 0:
        logger.warning("with_source.ingest_zero user=%s source=%s msg=%s", user_id, source, ingested.get("message"))
        # 仍尝试分析(可能已有历史数据)

    # 步骤 2: 触发 LLM 分析
    report = await _run_llm_analyze(user_id)

    logger.info(
        "with_source.success user=%s source=%s facts=%d report_id=%s",
        user_id, source, ingested["facts_imported"], report["id"],
    )

    return {
        "status": "success",
        "source": source,
        "ingested": ingested,
        "report": report,
    }
