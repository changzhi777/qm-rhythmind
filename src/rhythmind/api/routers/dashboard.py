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

router = APIRouter(prefix="", tags=["dashboard"])


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
        "湖南青沐生命科技有限公司 | 报告已经过处理和区块链数字水印加密可溯源",
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
