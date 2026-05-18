"""
api/routers/dashboard.py — 仪表盘 + AI 报告 API 端点

端点：
  GET  /api/dashboard       — 仪表盘汇总数据
  GET  /api/reports          — AI 分析报告列表（支持历史对比）
  GET  /api/reports/{id}     — 单篇报告详情
  GET  /api/reports/{id}/download — 下载报告 PDF
  POST /api/analyze          — 触发本地模型重新分析
"""
from __future__ import annotations

import io
import json
import logging
import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from rhythmind.api.deps import CurrentUserId
from rhythmind.core.memory.fact_manager import FactManager
from rhythmind.core.memory.models import HealthFact

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/qm/api", tags=["dashboard"])


def _fm(user_id: str) -> FactManager:
    """创建指定用户的 FactManager 实例。"""
    return FactManager(user_id)


@router.get("/dashboard")
async def get_dashboard(user_id: CurrentUserId) -> dict[str, Any]:
    """返回仪表盘汇总数据。"""
    fm = _fm(user_id)
    facts = await fm.get_all_current()
    data: dict[str, Any] = {}
    for f in facts:
        data[f"{f.subject}.{f.predicate}"] = f.object_json
    return {"status": "ok", "data": data}


@router.get("/reports")
async def list_reports(
    user_id: CurrentUserId,
    limit: int = 20,
) -> dict[str, Any]:
    """AI 分析报告列表（含历史）。"""
    fm = _fm(user_id)
    history = await fm.query_history("ai_report", "analysis", limit=limit)
    reports = []
    for f in history:
        obj = f.object_json
        if isinstance(obj, dict) and "content" in obj:
            reports.append({
                "id": f.id,
                "timestamp": obj.get("timestamp", ""),
                "model": obj.get("model", ""),
                "is_current": f.is_current,
                "preview": obj["content"][:200] + "..." if len(obj["content"]) > 200 else obj["content"],
            })
    return {"status": "ok", "reports": reports}


@router.get("/reports/{report_id}")
async def get_report(
    report_id: int,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    """单篇 AI 分析报告详情。"""
    fm = _fm(user_id)
    fact = await fm.get_fact_by_id(report_id)
    if not fact or fact.subject != "ai_report":
        raise HTTPException(status_code=404, detail="报告不存在")
    obj = fact.object_json
    return {
        "status": "ok",
        "report": {
            "id": fact.id,
            "content": obj.get("content", ""),
            "model": obj.get("model", ""),
            "timestamp": obj.get("timestamp", ""),
            "is_current": fact.is_current,
        },
    }


@router.get("/reports/{report_id}/download")
async def download_report_pdf(
    report_id: int,
    user_id: CurrentUserId,
) -> Response:
    """下载 AI 报告 PDF（文件名格式：用户ID_年月日时分秒.pdf）。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # 注册中文字体（STHeiti Light 支持中文，Hiragino TTC 格式不兼容）
    font_paths = [
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/STHeiti Light.ttc",
    ]
    font_name = "STHeiti"
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont(font_name, font_path))
                break
            except Exception:
                continue

    fm = _fm(user_id)
    fact = await fm.get_fact_by_id(report_id)
    if not fact or fact.subject != "ai_report":
        raise HTTPException(status_code=404, detail="报告不存在")

    # Parse object_json if it's a string
    obj = fact.object_json
    if isinstance(obj, str):
        obj = json.loads(obj)
    content = obj.get("content", "")
    model = obj.get("model", "")
    timestamp = obj.get("timestamp", "")

    # 生成文件名：用户ID_年月日时分秒.pdf
    dt = datetime.fromisoformat(timestamp) if timestamp else datetime.now()
    filename = f"{user_id}_{dt.strftime('%Y%m%d%H%M%S')}.pdf"

    def _generate_qr_image(data: str, size: int = 80) -> bytes:
        """生成二维码图片字节数据。"""
        import qrcode
        from io import BytesIO
        qr = qrcode.QRCode(version=1, box_size=4, border=1)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()

    # 构建 PDF - 使用 BaseDocTemplate + PageTemplate 控制页面
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
    from reportlab.platypus.flowables import Image
    from reportlab.lib.units import mm

    buffer = io.BytesIO()

    # 计算页面尺寸和边距
    page_width, page_height = A4  # 595.27 x 841.89 points
    left_margin = 20 * mm
    right_margin = 20 * mm
    top_margin = 20 * mm
    bottom_margin = 20 * mm

    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=left_margin,
        rightMargin=right_margin,
        topMargin=top_margin,
        bottomMargin=bottom_margin,
    )

    # 创建帧（内容区域，排除右上角二维码）
    content_width = page_width - left_margin - right_margin - 30 * mm  # 预留二维码宽度
    frame = Frame(
        left_margin, bottom_margin,
        content_width, page_height - top_margin - bottom_margin,
        id="content",
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )

    def on_page(canvas, doc):
        """每页绘制右上角二维码。"""
        canvas.saveState()
        # 报告右上角二维码
        qr_data = f"https://rhythmind.cn/report/{report_id}"
        qr_bytes = _generate_qr_image(qr_data, size=80)
        from reportlab.lib.utils import ImageReader
        img = ImageReader(io.BytesIO(qr_bytes))
        # 右上角位置
        qr_x = page_width - right_margin - 25 * mm
        qr_y = page_height - top_margin - 25 * mm
        canvas.drawImage(img, qr_x, qr_y, width=25 * mm, height=25 * mm, preserveAspectRatio=True)
        canvas.restoreState()

    page_template = PageTemplate(id="main", frames=[frame], onPage=on_page)
    doc.addPageTemplates([page_template])

    styles = getSampleStyleSheet()
    # Use explicit font for all custom styles
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=16,
        leading=20,
        spaceAfter=8,
    )
    heading2_style = ParagraphStyle(
        "CustomHeading2",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=13,
        leading=16,
        spaceAfter=6,
    )
    heading3_style = ParagraphStyle(
        "CustomHeading3",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=11,
        leading=14,
        spaceAfter=4,
    )
    meta_style = ParagraphStyle(
        "Meta",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=8,
        textColor="#666666",
        spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "CustomBody",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=10,
        leading=14,
        spaceAfter=4,
    )
    tip_style = ParagraphStyle(
        "Tip",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=8,
        textColor="#888888",
        leading=11,
        spaceAfter=4,
    )

    story = []
    story.append(Paragraph("RHYTHMIND 健康分析报告", title_style))
    story.append(Paragraph(f"生成时间：{timestamp} | 模型：{model}", meta_style))
    story.append(Spacer(1, 4 * mm))

    # 将 Markdown 内容转换为简单段落，并清理 LaTeX 数学语法
    import re
    def clean_latex(text: str) -> str:
        # 替换 \text{...} 为纯文本
        text = re.sub(r'\\text\{([^}]+)\}', r'\1', text)
        # 替换 \frac{...}{...} 为 .../...
        text = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'\1/\2', text)
        # 替换 \bf{...} 等加粗标记
        text = re.sub(r'\\bf\{([^}]+)\}', r'\1', text)
        # 移除多余的 $ 符号
        text = text.replace('$', '')
        return text

    # 截取内容控制长度（2页内）
    content_lines = content.split("\n")
    max_lines = 80  # 约2页内容量
    if len(content_lines) > max_lines:
        content_lines = content_lines[:max_lines]

    for line in content_lines:
        line = clean_latex(line).strip()
        if not line:
            story.append(Spacer(1, 3 * mm))
        elif line.startswith("# "):
            story.append(Paragraph(line[2:], title_style))
        elif line.startswith("## "):
            story.append(Paragraph(line[3:], heading2_style))
        elif line.startswith("### "):
            story.append(Paragraph(line[4:], heading3_style))
        elif line.startswith("- ") or line.startswith("* "):
            story.append(Paragraph(f"• {line[2:]}", body_style))
        else:
            story.append(Paragraph(line, body_style))

    # 添加结尾提示
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("━" * 28, meta_style))
    story.append(Paragraph(
        "💡 需要更专业指导和深度分析，请使用拍照上传的形式提供进阶数据或者订阅 Pro 套餐。",
        tip_style,
    ))
    story.append(Paragraph(
        "湖南青沐生命科技有限公司 | 报告已经过脱敏处理和区块链数字水印加密可溯源",
        tip_style,
    ))

    doc.build(story)
    buffer.seek(0)

    return Response(
        content=buffer.getvalue(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/analyze")
async def trigger_analysis(user_id: CurrentUserId) -> dict[str, Any]:
    """触发本地模型重新分析。"""
    from rhythmind.adapters.adapter_router import adapter_router
    from rhythmind.config import settings

    fm = _fm(user_id)
    facts = await fm.get_all_current()
    if not facts:
        raise HTTPException(status_code=400, detail="无数据，请先执行入库 (python scripts/run_ingestion.py)")

    import json
    from datetime import UTC, datetime

    fact_summary = []
    for f in facts:
        fact_summary.append(f"- [{f.subject}/{f.predicate}]: {json.dumps(f.object_json, ensure_ascii=False)}")

    system_prompt = """你是一位专业的运动健康 AI 分析师。根据用户的健康数据事实，生成一份专业的中文分析报告。

报告格式要求（Markdown）：
1. **总体评价**（1-2段）
2. **运动能力评估**（VO2Max、耐力、配速分析）
3. **健康风险评估**（心率、HRV、睡眠）
4. **训练负荷分析**（急性/慢性负荷比）
5. **赛事能力预测**（基于当前数据）
6. **个性化建议**（3-5条具体可执行的建议）

注意：
- 所有分析基于事实数据，不做无依据推测
- 如果某项数据异常，指出具体问题和建议
- 语言专业但不晦涩，适合运动爱好者阅读
- 报告长度控制在 800-1200 字"""

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
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.4,
            max_tokens=4096,
        )
    else:
        report_content = await adapter_router.chat(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
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
      {"subject": "profile", "predicate": "gender", "object_json": "MALE", "source": "garmin"},
      {"subject": "profile", "predicate": "vo2_max", "object_json": 52.0, "source": "garmin"},
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

    logger.info("import_facts user=%s imported=%d errors=%d", user_id, imported, len(errors))

    return {
        "status": "ok",
        "imported": imported,
        "errors": errors,
    }


# ── E2E 测试报告 ──────────────────────────────────────────

_TEST_REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "test_reports")
_TEST_REPORT_DIR = os.path.normpath(_TEST_REPORT_DIR)


@router.get("/test-reports")
async def list_test_reports(user_id: CurrentUserId) -> dict[str, Any]:
    """列出所有 E2E 测试报告。"""
    reports: list[dict[str, Any]] = []
    report_dir = _TEST_REPORT_DIR

    if not os.path.isdir(report_dir):
        return {"status": "ok", "reports": []}

    for entry in sorted(os.listdir(report_dir), reverse=True):
        entry_path = os.path.join(report_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        meta_path = os.path.join(entry_path, "meta.json")
        if not os.path.exists(meta_path):
            continue

        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except Exception:
            continue

        files: list[dict[str, Any]] = []
        for fname in os.listdir(entry_path):
            if fname == "meta.json":
                continue
            fpath = os.path.join(entry_path, fname)
            fsize = os.stat(fpath).st_size
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            files.append({
                "name": fname,
                "url": f"/qm/api/test-reports/{entry}/{fname}",
                "size_kb": round(fsize / 1024, 1),
                "type": ext,
            })

        reports.append({
            "id": entry,
            "timestamp": meta.get("timestamp", ""),
            "rounds": meta.get("rounds", 0),
            "total": meta.get("total", 0),
            "passed": meta.get("passed", 0),
            "failed": meta.get("failed", 0),
            "pass_rate": meta.get("pass_rate", 0.0),
            "page_avg_ms": meta.get("page_avg_ms", 0),
            "api_avg_ms": meta.get("api_avg_ms", 0),
            "files": sorted(files, key=lambda x: {"pdf": 0, "html": 1, "md": 2, "svg": 3}.get(x["type"], 9)),
        })

    return {"status": "ok", "reports": reports}


@router.get("/test-reports/{report_id}/{filename}")
async def download_test_report(report_id: str, filename: str, user_id: CurrentUserId):
    """下载测试报告文件。"""
    safe_report = report_id.replace("..", "").replace("/", "")
    safe_filename = filename.replace("..", "").replace("/", "")
    fpath = os.path.join(_TEST_REPORT_DIR, safe_report, safe_filename)

    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="文件不存在")

    from pathlib import Path
    from fastapi.responses import FileResponse

    mime_map = {
        ".pdf": "application/pdf",
        ".html": "text/html",
        ".md": "text/markdown",
        ".svg": "image/svg+xml",
    }
    ext = Path(safe_filename).suffix.lower()
    media_type = mime_map.get(ext, "application/octet-stream")

    return FileResponse(fpath, media_type=media_type, filename=safe_filename)


# ── 文件上传 + Chat 代理 ───────────────────────────────────

import base64
import csv
import io as _io
import shutil
import tempfile

from fastapi import File, UploadFile


def _pdf_to_images_b64(pdf_bytes: bytes, dpi: int = 150) -> list[dict[str, str]]:
    """将 PDF 每页转为 base64 编码的 PNG 图片。"""
    try:
        from pdf2image import convert_from_bytes
    except ImportError:
        raise RuntimeError("pdf2image 未安装，请执行: pip install pdf2image && brew install poppler")

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
        {"role": "system", "content": "你是专业的健康数据分析助手，擅长从医学报告和健康数据图片中提取结构化数据。只返回纯 JSON。"},
        {"role": "user", "content": content_parts},
    ]

    model_spec = settings.model_compliance_spec or "omlX://gemma-4-e4b-it-4bit"
    logger.info("vision analysis with model=%s images=%d", model_spec, len(images))

    if model_spec.startswith("omlX://"):
        from rhythmind.adapters.omlX_adapter import OMLXAdapter
        adapter = OMLXAdapter(model_spec[len("omlX://"):], timeout=120.0)
    else:
        adapter = adapter_router.route(model_spec)

    raw = await adapter.chat(messages, temperature=0.1, max_tokens=4096)

    # 清理 markdown 包裹的 JSON
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw_text": raw}


async def _write_vision_facts(
    fm: FactManager, subject_prefix: str, data: dict, filename: str,
) -> int:
    """将 AI 提取的结构化数据写入 FactManager。"""
    count = 0
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (str, int, float, bool)):
                await fm.write_fact(subject_prefix, key, value, source="vision_analysis")
                count += 1
            elif isinstance(value, dict):
                await fm.write_fact(subject_prefix, key, value, source="vision_analysis")
                count += 1
            elif isinstance(value, list):
                await fm.write_fact(subject_prefix, key, {"items": value}, source="vision_analysis")
                count += 1

    # 保存原始分析结果
    await fm.write_fact(subject_prefix, "_source", {"filename": filename, "extracted": count}, source="vision_analysis")
    return max(count, 1)


@router.post("/upload/file")
async def upload_file(
    file: UploadFile = File(...),
    user_id: CurrentUserId = None,
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
                    try:
                        val = float(val) if "." in val else int(val)
                    except ValueError:
                        pass
                    await fm.write_fact("upload_csv", f"{col}", val, source="file_upload")
                    facts_imported += 1
        summary = f"CSV {len(rows)} 行 × {len(cols)} 列，导入 {facts_imported} 条数据"

    elif ext == "json":
        data = json.loads(content)
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (str, int, float, bool)):
                    await fm.write_fact("upload_json", key, value, source="file_upload")
                    facts_imported += 1
                elif isinstance(value, dict):
                    await fm.write_fact("upload_json", key, value, source="file_upload")
                    facts_imported += 1
            summary = f"JSON 对象，导入 {facts_imported} 个字段"
        elif isinstance(data, list):
            facts_imported = len(data)
            await fm.write_fact("upload_json", "array_data", {"count": len(data)}, source="file_upload")
            summary = f"JSON 数组，{len(data)} 条记录"
        else:
            return {"status": "ok", "message": "不支持的 JSON 格式", "facts_imported": 0}

    elif ext == "txt":
        text = content.decode("utf-8", errors="replace")
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        await fm.write_fact("upload_text", "content", {"lines": len(lines), "preview": text[:500]}, source="file_upload")
        facts_imported = 1
        summary = f"文本文件，{len(lines)} 行"

    elif ext == "pdf":
        try:
            images_b64 = _pdf_to_images_b64(content)
            ai_result = await _analyze_with_vision(
                images_b64,
                "这是一份医学/健康 PDF 报告。请提取其中所有健康相关数据（如血液指标、身高体重、心率、血压、血糖、血脂等），以 JSON 格式返回。只返回 JSON，不要其他文字。",
            )
            facts_imported = await _write_vision_facts(fm, "pdf_report", ai_result, filename)
            summary = f"PDF 多模态分析完成，提取 {facts_imported} 条数据"
        except Exception as e:
            logger.warning("PDF vision analysis failed, fallback: %s", e)
            await fm.write_fact("upload_file", "pdf_received", {"filename": filename, "size": len(content)}, source="file_upload")
            facts_imported = 1
            summary = f"PDF 已接收（AI 分析暂不可用: {str(e)[:60]}）"

    elif ext in ("png", "jpg", "jpeg"):
        try:
            import base64
            img_b64 = base64.b64encode(content).decode("utf-8")
            mime = f"image/{'jpeg' if ext in ('jpg','jpeg') else ext}"
            ai_result = await _analyze_with_vision(
                [{"b64": img_b64, "mime": mime}],
                "这是一张健康/医学相关的图片（如化验单、体检报告、体脂秤读数等）。请提取其中所有健康数据，以 JSON 格式返回。只返回 JSON，不要其他文字。",
            )
            facts_imported = await _write_vision_facts(fm, "image_report", ai_result, filename)
            summary = f"图像多模态分析完成，提取 {facts_imported} 条数据"
        except Exception as e:
            logger.warning("Image vision analysis failed, fallback: %s", e)
            await fm.write_fact("upload_file", "image_received", {"filename": filename, "size": len(content), "type": ext}, source="file_upload")
            facts_imported = 1
            summary = f"图像已接收（AI 分析暂不可用: {str(e)[:60]}）"

    else:
        return {"status": "error", "message": f"不支持的文件格式: .{ext}", "facts_imported": 0}

    logger.info("upload_file user=%s file=%s facts=%d", user_id, filename, facts_imported)
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
    user_id: CurrentUserId = None,
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
            "status": result.status.value if hasattr(result.status, "value") else str(result.status),
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
                "data": {"coach_response": "暂无健康数据，请先通过上传页面导入数据文件，我才能为你提供健康分析。"},
            }

        fact_lines = [f"- [{f.subject}/{f.predicate}]: {json.dumps(f.object_json, ensure_ascii=False)}" for f in facts[:20]]
        return {
            "status": "ok",
            "message": "数据摘要",
            "data": {
                "coach_response": f"当前已录入 {len(facts)} 条健康数据：\n" + "\n".join(fact_lines),
            },
        }

