"""评分合并器 — 将硬规则和 LLM 结果合并为最终三档判断."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.c2_scorer.hard_rules import HardRuleVerdict
from src.c2_scorer.llm_scorer import LlmEvalResult
from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MergedVerdict:
    """合并后的最终判断结果."""

    final_verdict: str  # 推荐沟通 / 可以看看 / 不建议
    reason: str  # 推荐/拒绝理由摘要
    risks: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    hard_rule_passed: bool = True
    hard_rule_reject: bool = False
    llm_score: Optional[float] = None
    llm_verdict: Optional[str] = None


def merge_scores(
    hard_verdict: HardRuleVerdict,
    llm_result: Optional[LlmEvalResult],
    passing_score: int,
) -> MergedVerdict:
    """合并硬规则和 LLM 评估结果为最终三档判断.

    合并逻辑：
    1. 硬规则红线触发 → 直接"不建议"（跳过 LLM）
    2. 硬规则有不通过项（非红线）→ 直接"不建议"
    3. 硬规则通过 + LLM 出错或未提供 → "可以看看"（降级）
    4. 硬规则通过 + LLM 总分 ≥ passing_score*1.33 → "推荐沟通"
    5. 硬规则通过 + LLM 总分 ≥ passing_score → "可以看看"
    6. 硬规则通过 + LLM 总分 < passing_score → "不建议"

    Args:
        hard_verdict: 硬规则引擎输出.
        llm_result: LLM 评估输出（红线触发时可为 None）.
        passing_score: 岗位画像中的合格分数线.
    """
    risks: list[str] = []
    highlights: list[str] = []

    # 收集硬规则风险
    for r in hard_verdict.results:
        if r.passed is False:
            risks.append(f"[硬规则] {r.detail}")

    # 1/2. 硬规则不通过
    if hard_verdict.is_reject:
        reject_details = [
            r.detail for r in hard_verdict.results
            if r.is_red_flag and r.passed is False
        ]
        logger.info("merge_verdict", verdict="不建议", reason="red_flag_reject")
        return MergedVerdict(
            final_verdict="不建议",
            reason=f"触发红线规则: {'; '.join(reject_details)}",
            risks=risks,
            hard_rule_passed=False,
            hard_rule_reject=True,
        )

    if not hard_verdict.passed:
        fail_details = [
            r.detail for r in hard_verdict.results if r.passed is False
        ]
        logger.info("merge_verdict", verdict="不建议", reason="hard_rules_failed")
        return MergedVerdict(
            final_verdict="不建议",
            reason=f"硬规则不通过: {'; '.join(fail_details)}",
            risks=risks,
            hard_rule_passed=False,
        )

    # 硬规则通过，收集关键词亮点
    if hard_verdict.whitelist_hits:
        highlights.append(f"简历关键词命中: {', '.join(hard_verdict.whitelist_hits)}")

    # 3. LLM 未提供或出错 → 降级
    if llm_result is None or llm_result.error:
        error_msg = llm_result.error if llm_result else "LLM 未执行"
        logger.info("merge_verdict", verdict="可以看看", reason="llm_degraded")
        return MergedVerdict(
            final_verdict="可以看看",
            reason=f"硬规则通过，LLM 评估不可用（{error_msg}），降级处理",
            risks=risks,
            highlights=highlights,
        )

    # 收集 LLM 风险和亮点
    risks.extend(f"[LLM] {r}" for r in llm_result.risks)
    highlights.extend(f"[LLM] {h}" for h in llm_result.highlights)

    score = llm_result.weighted_total
    recommend_threshold = passing_score * 1.33

    # 4/5/6. 按 LLM 分数分档
    if score >= recommend_threshold:
        verdict = "推荐沟通"
        reason = f"LLM 总分 {score:.1f} ≥ 推荐线 {recommend_threshold:.0f}"
    elif score >= passing_score:
        verdict = "可以看看"
        reason = f"LLM 总分 {score:.1f}，在合格线 {passing_score} 和推荐线 {recommend_threshold:.0f} 之间"
    else:
        verdict = "不建议"
        reason = f"LLM 总分 {score:.1f} < 合格线 {passing_score}"

    logger.info("merge_verdict", verdict=verdict, llm_score=score, passing_score=passing_score)
    return MergedVerdict(
        final_verdict=verdict,
        reason=reason,
        risks=risks,
        highlights=highlights,
        llm_score=score,
        llm_verdict=llm_result.verdict,
    )
