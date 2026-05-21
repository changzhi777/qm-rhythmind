"""
observability/suggestion_engine.py — LLM 调用优化建议规则引擎

纯规则引擎（无 LLM），基于聚合指标生成优化建议。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Suggestion:
    title: str
    severity: str  # "info" | "warn" | "critical"
    detail: str
    metric_key: str
    current_value: float
    threshold: float


@dataclass
class ModelMetrics:
    model: str
    total_calls: int
    success_calls: int
    avg_latency_ms: float
    p95_latency_ms: float
    total_tokens: int
    total_cost: float
    output_input_ratio: float


def generate_suggestions(
    models: list[ModelMetrics],
    week_over_week_cost_delta: float | None = None,
    repeated_prompt_count: int = 0,
) -> list[Suggestion]:
    """基于聚合指标生成优化建议列表。"""
    suggestions: list[Suggestion] = []

    if not models:
        return suggestions

    avg_latency = sum(m.avg_latency_ms for m in models) / len(models)

    for m in models:
        # 规则 1：模型延迟对比
        if m.avg_latency_ms > avg_latency * 2 and avg_latency > 0:
            suggestions.append(Suggestion(
                title=f"{m.model} 延迟偏高",
                severity="warn",
                detail=(
                    f"{m.model} 平均延迟 {m.avg_latency_ms:.0f}ms，"
                    f"是全局均值 {avg_latency:.0f}ms 的 "
                    f"{m.avg_latency_ms / avg_latency:.1f}x，"
                    f"建议检查模型规格或切换更快的模型"
                ),
                metric_key="avg_latency_ms",
                current_value=m.avg_latency_ms,
                threshold=avg_latency * 2,
            ))

        # 规则 2：Token 利用率
        if 0 < m.output_input_ratio < 0.05 and m.total_calls > 10:
            suggestions.append(Suggestion(
                title=f"{m.model} Token 利用率低",
                severity="info",
                detail=(
                    f"{m.model} 输出/输入比仅 {m.output_input_ratio:.1%}，"
                    f"考虑缩减 max_tokens 或精简 prompt"
                ),
                metric_key="output_input_ratio",
                current_value=m.output_input_ratio,
                threshold=0.05,
            ))

        # 规则 3：错误率
        if m.total_calls > 0:
            error_rate = 1 - m.success_calls / m.total_calls
            if error_rate > 0.05:
                suggestions.append(Suggestion(
                    title=f"{m.model} 错误率异常",
                    severity="critical",
                    detail=(
                        f"{m.model} 失败率 {error_rate:.1%}（"
                        f"{m.total_calls - m.success_calls}/{m.total_calls}），"
                        f"检查上游 API Key、限流或模型可用性"
                    ),
                    metric_key="error_rate",
                    current_value=error_rate,
                    threshold=0.05,
                ))

    # 规则 4：成本周环比
    if week_over_week_cost_delta is not None and week_over_week_cost_delta > 0.3:
        suggestions.append(Suggestion(
            title="成本周环比增长",
            severity="warn",
            detail=(
                f"本周 Token 消耗增长 {week_over_week_cost_delta:.0%}，"
                f"建议检查是否有异常调用或优化 prompt 长度"
            ),
            metric_key="week_cost_delta",
            current_value=week_over_week_cost_delta,
            threshold=0.3,
        ))

    # 规则 5：重复 Prompt
    if repeated_prompt_count > 10:
        suggestions.append(Suggestion(
            title="重复 Prompt 调用过多",
            severity="info",
            detail=(
                f"相似 prompt 模板被调用 {repeated_prompt_count} 次/小时，"
                f"建议启用缓存或批量处理"
            ),
            metric_key="repeated_prompt_count",
            current_value=float(repeated_prompt_count),
            threshold=10.0,
        ))

    return suggestions
