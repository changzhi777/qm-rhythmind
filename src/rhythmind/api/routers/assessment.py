# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 跨领域评估 API (2026-07-07)
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────
#
# 端点:
#   POST /api/v1/assessment/start     — 启动评估,返回缺失维度
#   POST /api/v1/assessment/question  — LLM 出题(基于已收集答案)
#   POST /api/v1/assessment/complete  — 生成 3 维评分 + 综合建议
#
# 维度:
#   rehab     — 康复(基于《康复治疗师国家职业技能标准》)
#   nutrition — 营养(基于《公共营养师国家职业技能标准》)
#   training  — 运动(基于《社会体育指导员国家职业技能标准》)
#
# 流程:
#   start()   → question()×N → complete() → 写 health_fact + 返回 scores/advice
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rhythmind.api.deps import CurrentUserId
from rhythmind.api.routers._common import _fm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assessment", tags=["assessment"])

# ── 内存 session 存储(单进程) ──
# 生产环境应替换为 Redis 或 SQLite
_SESSIONS: dict[str, dict[str, Any]] = {}

MAX_QUESTIONS_PER_DIM = 3  # 每维度最多 3 题

# ── 三本国家标准核心指标 (摘要级,提示词模板) ──
_NATIONAL_STANDARDS_REF = """
[参考依据 - 2026-07-07 最新国标摘要]

## 康复治疗师 (2020 版)
- 评估: 运动功能(肌力/ROM/平衡)、感觉功能、认知、ADL
- 关键指标: Barthel 指数、FMA 运动评分、Ashworth 痉挛等级
- 治疗: 物理治疗(PT)、作业治疗(OT)、言语治疗(ST)

## 公共营养师 (2023 版)
- 评估: BMI、体脂率、膳食调查、生化(血糖/血脂)
- 关键指标: BMI 18.5-24 正常、25-28 超重、≥28 肥胖
- 营养: 三大宏量营养素配比、膳食纤维、特殊膳食(糖尿病/肾病)

## 社会体育指导员 (2019 版)
- 评估: 心肺耐力、肌力、柔韧、平衡、协调
- 关键指标: VO2max、静息心率、HRrest 储备
- 运动处方: FITT 原则(频率/强度/时间/类型)
"""


# ── 关键词映射 (用于判断数据维度覆盖) ──
DIMENSION_KEYWORDS = {
    "rehab": ["rehab", "recovery", "injury", "mobility", "pain"],
    "nutrition": ["nutrition", "diet", "food", "meal", "weight", "bmi"],
    "training": ["training", "fitness", "vo2max", "endurance", "activity"],
}

ALL_DIMENSIONS = ["rehab", "nutrition", "training"]


async def _aload_user_state(user_id: str) -> dict[str, Any]:
    """异步版: 读取用户 health_fact → flat dict。"""
    fm = _fm(user_id)
    facts = await fm.get_all_current()
    state: dict[str, Any] = {}
    for f in facts:
        if f.valid_until is not None:
            continue
        key = f"{f.subject}.{f.predicate}"
        obj = f.object_json
        if isinstance(obj, dict) and "value" in obj:
            state[key] = obj["value"]
        else:
            state[key] = obj
    return state


def _find_missing_dimensions(state: dict[str, Any]) -> list[str]:
    """基于关键词匹配,返回数据缺失的维度。"""
    missing: list[str] = []
    for dim, kws in DIMENSION_KEYWORDS.items():
        if not any(any(kw in k.lower() for kw in kws) for k in state):
            missing.append(dim)
    return missing or list(ALL_DIMENSIONS)


# ── 启动评估 ──

class StartResponse(BaseModel):
    session_id: str
    current_state: dict[str, Any] = Field(
        default_factory=dict,
        description="用户现有 health_fact 摘要 (key=value)",
    )
    missing_dimensions: list[str] = Field(
        default_factory=list,
        description="待评估的 3 维: rehab/nutrition/training",
    )


@router.post("/start", response_model=StartResponse)
async def assessment_start(user_id: CurrentUserId) -> StartResponse:
    """读取用户现有 health_fact,生成 session,返回待评估维度。"""
    current_state = await _aload_user_state(user_id)
    missing = _find_missing_dimensions(current_state)

    sid = str(uuid.uuid4())
    _SESSIONS[sid] = {
        "user_id": user_id,
        "answers": [],  # [{dimension, question, answer}, ...]
        "current_state": current_state,
        "dimension_index": 0,  # 当前评估到第几个维度
        "question_index": 0,  # 当前维度第几题
    }
    return StartResponse(
        session_id=sid,
        current_state=current_state,
        missing_dimensions=missing,
    )


# ── 出题 ──

class QuestionRequest(BaseModel):
    session_id: str
    answer: str = Field(..., description="用户上一题的回答(自由文本)")
    dimension: str = Field(..., description="rehab/nutrition/training")


class QuestionResponse(BaseModel):
    question: str
    options: list[str] = Field(
        default_factory=list,
        description="如选择题(可选),否则返回空",
    )
    is_final: bool = False
    dimension: str = ""


@router.post("/question", response_model=QuestionResponse)
async def assessment_question(body: QuestionRequest) -> QuestionResponse:
    """根据当前维度进度,LLM 出下一题。"""
    sess = _SESSIONS.get(body.session_id)
    if not sess:
        raise HTTPException(404, "session not found")
    if body.dimension not in ("rehab", "nutrition", "training"):
        raise HTTPException(400, "invalid dimension")

    # 记录答案
    sess["answers"].append({
        "dimension": body.dimension,
        "answer": body.answer[:500],  # 截断
    })
    sess["question_index"] += 1

    # 达到上限 → 提示 complete
    if sess["question_index"] >= MAX_QUESTIONS_PER_DIM:
        return QuestionResponse(
            question="评估完成,点击「生成综合建议」查看结果",
            is_final=True,
            dimension=body.dimension,
        )

    # LLM 出下一题(2026-07-07: oMLX 太慢,使用 fallback 题库)
    # TODO: 等更快的 LLM 部署后切回 LLM 出题
    DIM_NAMES = {
        "rehab": "康复",
        "nutrition": "营养",
        "training": "运动",
    }
    # Fallback 题库(每维度 3 题,智能跳过)
    FALLBACK_QUESTIONS = {
        "rehab": [
            {"question": "过去 3 个月是否有持续性关节/肌肉疼痛?", "options": ["A. 没有", "B. 偶尔", "C. 经常", "D. 每天"]},
            {"question": "是否能独立完成日常活动(穿衣/吃饭/行走)?", "options": ["A. 完全独立", "B. 偶尔需要帮助", "C. 经常需要帮助", "D. 完全需要"]},
            {"question": "是否有医生诊断的慢性疾病(高血压/糖尿病等)?", "options": ["A. 没有", "B. 1 种", "C. 2 种", "D. 3 种及以上"]},
        ],
        "nutrition": [
            {"question": "每天吃几餐?是否规律吃早餐?", "options": ["A. 3 餐+早餐", "B. 2-3 餐", "C. 1-2 餐", "D. 不规律"]},
            {"question": "每天饮水约多少升?", "options": ["A. >2L", "B. 1.5-2L", "C. 1-1.5L", "D. <1L"]},
            {"question": "最近一周吃蔬菜水果的频率?", "options": ["A. 每天", "B. 5-6 次", "C. 3-4 次", "D. <3 次"]},
        ],
        "training": [
            {"question": "每周运动几次?每次多少分钟?", "options": ["A. 5+ 次/30+ 分钟", "B. 3-4 次/30+ 分钟", "C. 1-2 次", "D. 偶尔"]},
            {"question": "运动时心率大概多少?", "options": ["A. <120", "B. 120-150", "C. 150-170", "D. >170"]},
            {"question": "运动后是否容易气喘或疲劳?", "options": ["A. 几乎不", "B. 偶尔", "C. 经常", "D. 每次都"]},
        ],
    }
    q_idx = sess["question_index"]
    fb_list = FALLBACK_QUESTIONS.get(body.dimension, [])
    if q_idx < len(fb_list):
        q = fb_list[q_idx]
        return QuestionResponse(
            question=q["question"],
            options=q["options"],
            is_final=False,
            dimension=body.dimension,
        )
    # 题库用完 → 完成
    return QuestionResponse(
        question="评估完成,点击「生成综合建议」查看结果",
        is_final=True,
        dimension=body.dimension,
    )


# ── 完成评估 ──

class CompleteRequest(BaseModel):
    session_id: str
    force: bool = Field(
        default=False,
        description="是否强制完成(跳过剩余问题)",
    )


class CompleteResponse(BaseModel):
    scores: dict[str, int] = Field(
        ...,
        description="3 维评分 0-100: rehab/nutrition/training",
    )
    advice: str = Field(..., description="跨领域综合建议 (Markdown)")
    summary: dict[str, Any] = Field(
        default_factory=dict,
        description="评估概要 (等级 + 重点 + 风险)",
    )


def _parse_score(text: str, dim: str) -> int:
    """从 LLM 输出中提取 0-100 分数,容错解析。"""
    import re
    # 找 "康复 75 分" 或 "rehab: 75" 等
    m = re.search(rf"({dim}[:：\s]*)(\d{{1,3}})", text, re.IGNORECASE)
    if m:
        score = int(m.group(2))
        return max(0, min(100, score))
    return 50  # 默认中等


def _generate_fallback_advice(
    answers_by_dim: dict[str, list[str]],
    current_state: dict[str, Any],
) -> str:
    """LLM 失败时的 fallback - 基于现有数据 + 答案生成模板化建议。

    不调用 LLM,保证评估功能可用性。基于:
    1. 三本国家职业技能标准的核心指标
    2. 用户现有 health_fact
    3. 问卷答案关键词
    """
    # 基于现有数据计算启发式分数
    def calc_nutrition() -> int:
        score = 60
        bmi = current_state.get("profile.bmi", 0)
        if isinstance(bmi, (int, float)) and 18.5 <= bmi <= 24:
            score += 15
        if current_state.get("sleep.avg_total_hours", 0) >= 7:
            score += 10
        return min(100, max(0, score))

    def calc_training() -> int:
        score = 60
        vo2 = current_state.get("profile.vo2_max", 0)
        if isinstance(vo2, (int, float)) and vo2 >= 50:
            score += 20
        acwr = current_state.get("training.acwr", 0)
        if isinstance(acwr, (int, float)) and 0.8 <= acwr <= 1.3:
            score += 10
        readiness = current_state.get("training.readiness_score", 0)
        if isinstance(readiness, (int, float)) and readiness >= 70:
            score += 10
        return min(100, max(0, score))

    def calc_rehab() -> int:
        # 基础分 60
        score = 60
        # 有训练准备度/ACWR 间接反映恢复能力
        readiness = current_state.get("training.readiness_score", 0)
        if isinstance(readiness, (int, float)) and readiness >= 70:
            score += 20
        # 问卷答案分析
        for ans in answers_by_dim.get("rehab", []):
            ans_lower = ans.lower()
            if "没有" in ans_lower or "正常" in ans_lower or "可以" in ans_lower:
                score += 10
            elif "有" in ans_lower or "疼" in ans_lower or "困难" in ans_lower:
                score -= 15
        return min(100, max(20, score))

    # 简化 - 直接给 3 维分数,LLM 已经失败用 fallback
    # 但 LLM 流程不调,需要直接算分数
    # 让 _parse_score 处理无 LLM 的情况
    pass


def _calculate_fallback_scores(
    answers_by_dim: dict[str, list[str]],
    current_state: dict[str, Any],
) -> dict[str, int]:
    """无 LLM 时的启发式评分。"""
    scores = {"rehab": 60, "nutrition": 60, "training": 60}

    # nutrition
    bmi = current_state.get("profile.bmi", 0)
    if isinstance(bmi, (int, float)) and 18.5 <= bmi <= 24:
        scores["nutrition"] += 15
    if current_state.get("sleep.avg_total_hours", 0) >= 7:
        scores["nutrition"] += 10

    # training
    vo2 = current_state.get("profile.vo2_max", 0)
    if isinstance(vo2, (int, float)) and vo2 >= 50:
        scores["training"] += 20
    acwr = current_state.get("training.acwr", 0)
    if isinstance(acwr, (int, float)) and 0.8 <= acwr <= 1.3:
        scores["training"] += 10
    readiness = current_state.get("training.readiness_score", 0)
    if isinstance(readiness, (int, float)) and readiness >= 70:
        scores["training"] += 10

    # rehab (问卷驱动)
    for ans in answers_by_dim.get("rehab", []):
        ans_lower = ans.lower()
        if "没有" in ans_lower or "正常" in ans_lower or "可以" in ans_lower:
            scores["rehab"] += 10
        elif "有" in ans_lower or "疼" in ans_lower or "困难" in ans_lower:
            scores["rehab"] -= 15

    return {k: max(20, min(100, v)) for k, v in scores.items()}


@router.post("/complete", response_model=CompleteResponse)
async def assessment_complete(body: CompleteRequest) -> CompleteResponse:
    """生成 3 维评分 + 综合建议,写入 health_fact。"""
    sess = _SESSIONS.get(body.session_id)
    if not sess:
        raise HTTPException(404, "session not found")
    user_id = sess["user_id"]

    # 收集所有答案
    answers_by_dim: dict[str, list[str]] = {"rehab": [], "nutrition": [], "training": []}
    for a in sess["answers"]:
        answers_by_dim[a["dimension"]].append(a["answer"])

    # LLM 生成评分 + 建议
    from rhythmind.adapters.adapter_router import adapter_router
    from rhythmind.config import settings

    user_data_str = json.dumps(sess["current_state"], ensure_ascii=False)[:800]
    answers_str = "\n".join(
        f"[{dim}]\n" + "\n".join(f"  Q: {a}" for a in ans)
        for dim, ans in answers_by_dim.items()
    )

    system_prompt = f"""你是 RHYTHMIND 健康评估师。基于 3 本国家职业技能标准做综合评估。
{_NATIONAL_STANDARDS_REF}

任务: 给用户出 3 维评分(0-100)和简短建议。
输出格式(纯文本):
康复: <0-100 数字>
营养: <0-100 数字>
运动: <0-100 数字>

[建议]
<500 字内,3 维各 1 段,引国标>
"""
    user_prompt = f"""用户已有数据: {user_data_str}

问卷答案:
{answers_str}

请输出评分和建议。"""

    # 调 LLM(失败用 fallback)
    # 2026-07-07: oMLX gemma-4-12B-it-4bit 推理 ~60s 必超时,先用 fallback
    # TODO: 等生产环境 oMLX 升级或换更快的模型后再开启 LLM
    use_llm = body.force  # 用户显式 force=True 才调 LLM
    reply = ""
    if use_llm:
        try:
            from rhythmind.adapters.omlX_adapter import OMLXAdapter

            spec = settings.model_primary_spec
            adapter = OMLXAdapter(
                spec.replace("omlX://", ""),
                base_url=settings.omlX_base_url,
                timeout=30.0,
            )
            reply = await adapter.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.5,
                max_tokens=500,
            )
        except Exception as e:
            logger.warning("LLM 失败,用 fallback: %s", e)
            reply = ""

    # 解析分数(LLM 失败用 fallback)
    is_fallback = reply == "" or "调用失败" in reply or "timeout" in reply.lower()
    cur_state = sess.get("current_state", {})
    if is_fallback:
        scores = _calculate_fallback_scores(answers_by_dim, cur_state)
        reply = (
            f"康复: {scores['rehab']}\n"
            f"营养: {scores['nutrition']}\n"
            f"运动: {scores['training']}\n\n"
            f"[建议] (基于启发式评分,LLM 推理暂不可用)\n\n"
            f"**康复**: 当前评估基于您的健康数据。"
            f"建议增加日常功能性活动(步行/伸展),保持关节灵活性。\n\n"
            f"**营养**: BMI 在{'正常' if 18.5 <= cur_state.get('profile.bmi', 0) <= 24 else '需要关注'}范围。"
            f"建议保持均衡饮食,关注蛋白质和蔬菜摄入。\n\n"
            f"**运动**: VO2max {cur_state.get('profile.vo2_max', 'N/A')}。"
            f"建议保持每周 3-4 次有氧训练,关注恢复。"
        )
    else:
        scores = {
            "rehab": _parse_score(reply, "康复"),
            "nutrition": _parse_score(reply, "营养"),
            "training": _parse_score(reply, "运动"),
        }

    # 等级标签
    def level(s: int) -> str:
        if s >= 80:
            return "优秀"
        if s >= 60:
            return "良好"
        if s >= 40:
            return "一般"
        return "需改善"

    summary = {
        "levels": {k: level(v) for k, v in scores.items()},
        "total_questions": len(sess["answers"]),
        "evaluated_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
    }

    # 写 health_fact
    fm = _fm(user_id)
    await fm.write_fact(
        "assessment", "overall",
        {
            "rehab_score": scores["rehab"],
            "nutrition_score": scores["nutrition"],
            "training_score": scores["training"],
            "summary": summary,
        },
        source="cross_domain_assessment",
    )
    await fm.write_fact(
        "assessment", "rehab_score",
        scores["rehab"],
        source="cross_domain_assessment",
    )
    await fm.write_fact(
        "assessment", "nutrition_score",
        scores["nutrition"],
        source="cross_domain_assessment",
    )
    await fm.write_fact(
        "assessment", "training_score",
        scores["training"],
        source="cross_domain_assessment",
    )
    await fm.write_fact(
        "assessment", "advice",
        reply,
        source="cross_domain_assessment",
    )

    # 清理 session
    del _SESSIONS[body.session_id]

    return CompleteResponse(
        scores=scores,
        advice=reply,
        summary=summary,
    )


# ── 状态查询 (调试用) ──

@router.get("/session/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    sess = _SESSIONS.get(session_id)
    if not sess:
        raise HTTPException(404, "session not found")
    return {
        "user_id": sess["user_id"],
        "answers_count": len(sess["answers"]),
        "current_dimension_index": sess["dimension_index"],
        "current_question_index": sess["question_index"],
    }
