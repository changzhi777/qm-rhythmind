"""
api/routers/reports.py — AI 报告 + E2E 测试报告 API 端点

端点：
  GET  /qm/api/reports                       — AI 分析报告列表（含历史对比）
  GET  /qm/api/reports/{report_id}            — 单篇报告详情
  GET  /qm/api/reports/{report_id}/download   — 下载报告 PDF（含 QR 码水印）
  GET  /qm/api/test-reports                  — E2E 测试报告列表
  GET  /qm/api/test-reports/{report_id}/{filename} — 下载测试报告文件
"""
from __future__ import annotations

import io
import json
import logging
import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from rhythmind.api.deps import CurrentUserId
from rhythmind.api.routers._common import _fm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/qm/api", tags=["reports"])


# ── E2E 测试报告目录常量 ──────────────────────────────────────────

_TEST_REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "test_reports")
_TEST_REPORT_DIR = os.path.normpath(_TEST_REPORT_DIR)


# ── AI 分析报告 ──────────────────────────────────────────────────


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


def _generate_qr_image(data: str, size: int = 80) -> bytes:
    """生成二维码图片字节数据。"""
    from io import BytesIO

    import qrcode

    qr = qrcode.QRCode(version=1, box_size=4, border=1)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


@router.get("/reports/{report_id}/download")
async def download_report_pdf(
    report_id: int,
    user_id: CurrentUserId,
) -> Response:
    """下载 AI 报告 PDF（文件名格式：用户ID_年月日时分秒.pdf）。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, Spacer

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

    # 构建 PDF - 使用 BaseDocTemplate + PageTemplate 控制页面
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate

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

    def on_page(canvas, doc) -> None:
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
        text = re.sub(r"\\text\{([^}]+)\}", r"\1", text)
        # 替换 \frac{...}{...} 为 .../...
        text = re.sub(r"\\frac\{([^}]+)\}\{([^}]+)\}", r"\1/\2", text)
        # 替换 \bf{...} 等加粗标记
        text = re.sub(r"\\bf\{([^}]+)\}", r"\1", text)
        # 移除多余的 $ 符号
        text = text.replace("$", "")
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


# ── E2E 测试报告 ──────────────────────────────────────────────────


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

    mime_map = {
        ".pdf": "application/pdf",
        ".html": "text/html",
        ".md": "text/markdown",
        ".svg": "image/svg+xml",
    }
    ext = Path(safe_filename).suffix.lower()
    media_type = mime_map.get(ext, "application/octet-stream")

    return FileResponse(fpath, media_type=media_type, filename=safe_filename)
