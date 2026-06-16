# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Privacy router (GDPR / PIPL endpoints)
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────

"""
api/routers/privacy.py — 数据主体权利接口

Endpoints:
  GET  /privacy/export   — 当前登录用户拉取自己的数据（JSON）
  POST /privacy/delete   — 当前登录用户请求永久删除自己的数据
  GET  /privacy/policy   — 静态隐私政策入口（仅返回 URL，便于前端引用）

安全要点:
  - 必须经过鉴权（CurrentUserId）；不能"代删别人"
  - delete 强制要求 confirm_token == user_id（简易二次确认；
    生产可升级为 email OTP / TOTP）
  - 限流（与其它写接口同一档次），防滥用脚本扫
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from rhythmind.api.deps import CurrentUserId
from rhythmind.api.rate_limit import rate_limit_user
from rhythmind.privacy import PrivacyService  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/privacy", tags=["privacy"])

# 限流：每用户每小时 5 次，避免脚本批量打爆
_export_limit = [Depends(rate_limit_user("privacy_export", 5, 3600))]
_delete_limit = [Depends(rate_limit_user("privacy_delete", 3, 3600))]


# ── Schemas ─────────────────────────────────────────────────────────────────

class DeleteRequest(BaseModel):
    confirm_token: str  # 必须等于当前 user_id


class PrivacyPolicyResponse(BaseModel):
    policy_url: str
    contact_email: str
    last_updated: str


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get(
    "/export",
    summary="导出当前用户的全部个人数据（JSON）",
    response_class=Response,                 # 直接返回 application/json
    responses={
        200: {
            "description": "用户数据 JSON 包",
            "content": {"application/json": {"schema": {"type": "object"}}},
        },
    },
    dependencies=_export_limit,
)
async def export_my_data(user_id: CurrentUserId) -> Response:
    """
    返回 application/json 的完整数据导出。

    Content-Disposition 设为 attachment，方便浏览器直接保存为文件。
    """
    svc = PrivacyService()
    bundle = await svc.export_user_data(user_id)
    payload = json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2)

    logger.info("privacy.export.completed user_id=%s bytes=%d", user_id, len(payload))
    try:
        from rhythmind.audit import AuditEvent, audit_log  # type: ignore[attr-defined]
        audit_log(
            AuditEvent.PRIVACY_EXPORT,
            user_id=user_id,
            bytes=len(payload),
            memory_rows=len(bundle.agent_memory),
            facts_rows=len(bundle.health_facts),
        )
    except Exception:
        pass

    return Response(
        content=payload,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="rhythmind_export_{user_id}.json"',  # noqa: E501
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/delete",
    summary="永久删除当前用户的全部个人数据（不可逆）",
    dependencies=_delete_limit,
)
async def delete_my_data(
    req: DeleteRequest,
    user_id: CurrentUserId,
) -> JSONResponse:
    """
    `confirm_token` 必须等于当前 `user_id` 才会执行；否则 400。
    返回 200 + DeletionReport，即使部分存储删除失败也会返回（is_clean=false）。
    """
    if req.confirm_token != user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="confirm_token must equal your user_id to proceed",
        )

    svc = PrivacyService()
    report = await svc.delete_user_data(user_id, confirm_token=req.confirm_token)

    # 关键安全审计日志：包含 user_id 与每个存储的成功/失败
    logger.warning(
        "privacy.delete.completed user_id=%s clean=%s",
        user_id, report.is_clean,
    )
    try:
        from rhythmind.audit import AuditEvent, audit_log  # type: ignore[attr-defined]
        audit_log(
            AuditEvent.PRIVACY_DELETE if report.is_clean else AuditEvent.PRIVACY_DELETE_FAILURE,  # noqa: E501
            user_id=user_id,
            successes=len(report.successes),
            failures=len(report.failures),
            failure_stores=[s for s, _ in report.failures],
        )
    except Exception:
        pass

    return JSONResponse(
        status_code=200,
        content=report.to_dict(),
    )


@router.get(
    "/policy",
    response_model=PrivacyPolicyResponse,
    summary="获取隐私政策入口（静态信息）",
)
async def privacy_policy() -> PrivacyPolicyResponse:
    return PrivacyPolicyResponse(
        policy_url="https://rhythmind.ai/privacy",
        contact_email="14455975@qq.com",
        last_updated="2026-05-09",
    )
