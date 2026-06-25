# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
api/routers/chat.py — 直接 LLM 对话端点(2026-06-25)

背景:
  原 /api/v1/health/chat 是"意图分类 + 工作流路由"模式,
  实际应答由 HealthRouter → HermesBase.run() 三阶段 Swarm 流水线生成,
  对纯自由对话的"算力"体验不好。

  本端点直接调 adapter_router.chat() (oMLX = 当前算力后台),
  支持多轮 history,系统 prompt 注入"健康助手"人设,
  适合自由问答 + 健康建议场景。

使用:
  POST /api/v1/llm/chat
  {
    "message": "我的训练准备度如何?",
    "history": [                              // 可选,多轮对话
      {"role": "user", "content": "..."},
      {"role": "assistant", "content": "..."}
    ]
  }
  →
  {
    "reply": "根据你最近 7 天的数据,...",
    "model": "omlX://gemma-4-12B-it-4bit",
    "latency_ms": 12500
  }
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rhythmind.api.deps import CurrentUserId
from rhythmind.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm", tags=["chat"])

# 系统 prompt(健康助手人设)
_SYSTEM_PROMPT = """你是 RHYTHMIND 律动的健康助手,基于用户的多智能体健康平台。

你的职责:
  - 回答用户关于训练、跑步、睡眠、营养、伤病预防的健康问题
  - 解释健康数据指标(VO2 Max、配速、心率、HRV、睡眠质量等)
  - 提供基于科学的训练建议(切勿给出极端或医疗处方)
  - 引用用户的实际数据时,用"根据你的最近数据"等口吻

回答风格:
  - 中文,简洁清晰,200-400 字以内
  - 用 Markdown 格式,关键数据用粗体
  - 不要捏造数据,不确定时说"建议查看完整数据"
  - 涉及医疗建议时提醒"咨询专业医生"
"""

# 安全:限制单次 message 长度(防 token 滥用)
MAX_MESSAGE_LEN = 2000
MAX_HISTORY = 10  # 最多 10 轮历史


class ChatMessage(BaseModel):
    role: str = Field(..., description="user | assistant")
    content: str = Field(..., max_length=MAX_MESSAGE_LEN)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LEN, description="用户消息")
    history: list[ChatMessage] = Field(default_factory=list, description="多轮历史(最多 10 轮)")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="采样温度")
    max_tokens: int = Field(default=1024, ge=64, le=4096, description="最大输出 token")


class ChatResponse(BaseModel):
    reply: str
    model: str
    latency_ms: int
    usage: dict[str, int] = Field(default_factory=dict)


@router.post(
    "/chat",
    summary="直接 LLM 对话(算力后台)",
    description="直接调用 oMLX (settings.model_primary_spec) 进行多轮对话,"
    "不走 Swarm 工作流。",
    responses={
        200: {"description": "对话成功"},
        401: {"description": "未授权"},
        502: {"description": "算力后端调用失败"},
    },
)
async def direct_llm_chat(
    body: ChatRequest,
    user_id: CurrentUserId,
) -> ChatResponse:
    """
    直接调 oMLX (gemma-4-12B-it-4bit) 进行多轮对话。
    """
    # 1. 构造 messages(系统 + 历史 + 当前)
    messages: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    # 截断历史到 MAX_HISTORY
    history = body.history[-MAX_HISTORY:] if body.history else []
    for h in history:
        if h.role in ("user", "assistant") and h.content:
            messages.append({"role": h.role, "content": h.content})
    messages.append({"role": "user", "content": body.message})

    # 2. 调算力后台(adapter_router = oMLX)
    from rhythmind.adapters.adapter_router import adapter_router

    spec = settings.model_primary_spec
    logger.info(
        "llm_chat request user=%s spec=%s msg_len=%d history=%d",
        user_id, spec, len(body.message), len(history),
    )

    start = time.perf_counter()
    try:
        reply = await adapter_router.chat(
            messages=messages,
            model_spec=spec,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )
    except Exception as e:
        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.exception("llm_chat failed: user=%s err=%s", user_id, e)
        raise HTTPException(
            status_code=502,
            detail=f"算力后端调用失败: {type(e).__name__}: {str(e)[:200]}",
        ) from e

    latency_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "llm_chat success user=%s latency=%dms reply_len=%d",
        user_id, latency_ms, len(reply),
    )

    return ChatResponse(
        reply=reply,
        model=spec,
        latency_ms=latency_ms,
    )
