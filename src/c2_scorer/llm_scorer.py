"""DeepSeek V3 LLM 评估层 — 基于岗位画像 prompt 模板对候选人做软性评估."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import AsyncOpenAI, APITimeoutError, APIConnectionError

from src.c2_scorer.profile_loader import JobProfile
from src.common.config import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MAX_RETRIES = 2


# ───────── 数据结构 ─────────


@dataclass
class DimensionScore:
    """单个评估维度的得分."""

    name: str
    score: int
    weight: int
    reason: str = ""


@dataclass
class LlmEvalResult:
    """LLM 评估结果."""

    dimension_scores: list[DimensionScore] = field(default_factory=list)
    weighted_total: float = 0.0
    verdict: str = ""  # 由 score_merger 决定，LLM 不再返回此字段
    risks: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    raw_output: str = ""
    error: Optional[str] = None


# ───────── Prompt 渲染 ─────────


def render_hard_rules_summary(profile: JobProfile) -> str:
    """将硬规则配置渲染为人类可读的摘要文本."""
    hr = profile.hard_rules
    lines = [
        f"- 年龄要求：{hr.age_range.min}-{hr.age_range.max} 岁",
        f"- 学历要求：{hr.education_min}",
        f"- 薪资范围：试用期 {hr.salary_range.probation_min}-{hr.salary_range.probation_max} 元/月，"
        f"转正 {hr.salary_range.regular_min}-{hr.salary_range.regular_max} 元/月",
    ]
    if hr.experience_required:
        min_y = hr.experience_min_years or 0
        lines.append(f"- 工作经验：需要 {min_y} 年以上相关经验")
    else:
        lines.append("- 工作经验：不限")
    if hr.accept_early_morning:
        lines.append("- 需接受凌晨上班（03:00-06:30）")
    if hr.accept_store_transfer:
        lines.append("- 需接受调店安排")
    return "\n".join(lines)


def render_dimensions_detail(profile: JobProfile) -> str:
    """将评估维度渲染为详细说明文本."""
    lines = []
    for dim in profile.llm_evaluation.dimensions:
        lines.append(f"### {dim.name}（权重 {dim.weight}%）")
        lines.append(dim.description.strip())
        lines.append("")
    return "\n".join(lines)


def render_prompt(profile: JobProfile, candidate_text: str) -> tuple[str, str]:
    """渲染完整的 LLM 评估 prompt.

    Args:
        profile: 岗位画像配置.
        candidate_text: 候选人简历/信息的文本描述.
    """
    system_prompt = profile.llm_evaluation.prompt_template.format(
        position_name=profile.position_name,
        hard_rules_summary=render_hard_rules_summary(profile),
        dimensions_detail=render_dimensions_detail(profile),
    )
    return system_prompt, candidate_text


# ───────── 响应解析 ─────────

_RESPONSE_FORMAT_INSTRUCTION = """
请严格以如下 JSON 格式返回评估结果（不要包含其他内容）：
{
  "dimension_scores": [
    {"name": "维度名称", "score": 0-100, "reason": "打分理由"}
  ],
  "weighted_total": 加权总分,
  "risks": ["风险点1", "风险点2"],
  "highlights": ["亮点1", "亮点2"]
}

加权总分计算公式：weighted_total = Σ(各维度 score × 该维度 weight) / 100
例如：维度A 得 80 分权重 30%，维度B 得 60 分权重 70%，则 weighted_total = (80×30 + 60×70) / 100 = 66.0

注意：不需要给出最终推荐结论（推荐沟通/可以看看/不建议），只需打分和列出风险亮点。
"""


def parse_llm_response(
    raw_output: str, profile: JobProfile
) -> LlmEvalResult:
    """解析 LLM 返回的 JSON 文本为 LlmEvalResult."""
    # 尝试提取 JSON 块（LLM 可能包裹在 markdown code block 中）
    text = raw_output.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1]
        text = text.split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1]
        text = text.split("```", 1)[0]

    try:
        data: dict[str, Any] = json.loads(text.strip())
    except json.JSONDecodeError as exc:
        return LlmEvalResult(
            raw_output=raw_output,
            error=f"JSON 解析失败: {exc}",
        )

    dim_map = {d.name: d.weight for d in profile.llm_evaluation.dimensions}
    dimension_scores = []
    for item in data.get("dimension_scores", []):
        name = item.get("name", "")
        dimension_scores.append(DimensionScore(
            name=name,
            score=int(item.get("score", 0)),
            weight=dim_map.get(name, 0),
            reason=item.get("reason", ""),
        ))

    return LlmEvalResult(
        dimension_scores=dimension_scores,
        weighted_total=float(data.get("weighted_total", 0)),
        verdict=data.get("verdict", ""),
        risks=data.get("risks", []),
        highlights=data.get("highlights", []),
        raw_output=raw_output,
    )


# ───────── LLM 评估器 ─────────


class LlmScorer:
    """DeepSeek V3 LLM 评估器."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = _DEFAULT_MODEL,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(
            api_key=api_key or settings.deepseek_api_key,
            base_url=base_url or settings.deepseek_base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._model = model

    async def evaluate(
        self,
        profile: JobProfile,
        candidate_text: str,
    ) -> LlmEvalResult:
        """调用 LLM 对候选人进行软性评估.

        Args:
            profile: 岗位画像配置.
            candidate_text: 候选人简历/信息的文本描述.

        Returns:
            LlmEvalResult，包含各维度评分、总分、结论、风险和亮点。
            API 异常时返回带 error 字段的降级结果。
        """
        system_prompt, user_content = render_prompt(profile, candidate_text)

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt + "\n" + _RESPONSE_FORMAT_INSTRUCTION,
                    },
                    {"role": "user", "content": f"## 候选人信息\n{user_content}"},
                ],
                temperature=0.1,
            )
        except (APITimeoutError, APIConnectionError) as exc:
            logger.warning("LLM API 调用失败: %s", exc)
            return LlmEvalResult(error=f"API 调用失败: {exc}")
        except Exception as exc:
            logger.exception("LLM API 未知错误")
            return LlmEvalResult(error=f"未知错误: {exc}")

        raw_output = response.choices[0].message.content or ""
        return parse_llm_response(raw_output, profile)
