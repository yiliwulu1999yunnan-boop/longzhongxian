"""Tests for c2_scorer.score_merger — 评分合并器."""

from src.c2_scorer.hard_rules import HardRuleVerdict, RuleResult
from src.c2_scorer.llm_scorer import DimensionScore, LlmEvalResult
from src.c2_scorer.score_merger import merge_scores


def _passing_hard_verdict() -> HardRuleVerdict:
    """硬规则全部通过的 verdict."""
    return HardRuleVerdict(
        passed=True,
        is_reject=False,
        results=[
            RuleResult(rule_name="age_range", passed=True, detail="年龄 25 在范围内"),
            RuleResult(rule_name="education_min", passed=True, detail="学历达标"),
        ],
        whitelist_hits=["餐饮", "面点"],
        blacklist_hits=[],
    )


def _red_flag_hard_verdict() -> HardRuleVerdict:
    """硬规则触发红线的 verdict."""
    return HardRuleVerdict(
        passed=False,
        is_reject=True,
        results=[
            RuleResult(
                rule_name="job_hopping",
                passed=False,
                is_red_flag=True,
                detail="近一年 4 份工作，频繁跳槽",
            ),
        ],
    )


def _fail_hard_verdict() -> HardRuleVerdict:
    """硬规则不通过（非红线）的 verdict."""
    return HardRuleVerdict(
        passed=False,
        is_reject=False,
        results=[
            RuleResult(
                rule_name="industry_keywords",
                passed=False,
                detail="命中黑名单关键词: KTV",
            ),
        ],
    )


def _high_score_llm() -> LlmEvalResult:
    """LLM 高分结果（总分 85）."""
    return LlmEvalResult(
        dimension_scores=[
            DimensionScore(name="能早起", score=90, weight=15, reason="好"),
        ],
        weighted_total=85.0,
        verdict="推荐沟通",
        risks=[],
        highlights=["有 3 年面点经验"],
    )


def _mid_score_llm() -> LlmEvalResult:
    """LLM 中等分结果（总分 65）."""
    return LlmEvalResult(
        dimension_scores=[],
        weighted_total=65.0,
        verdict="可以看看",
        risks=["换工作频繁"],
        highlights=[],
    )


def _low_score_llm() -> LlmEvalResult:
    """LLM 低分结果（总分 40）."""
    return LlmEvalResult(
        dimension_scores=[],
        weighted_total=40.0,
        verdict="不建议",
        risks=["完全无相关经验"],
        highlights=[],
    )


def _error_llm() -> LlmEvalResult:
    """LLM 出错结果."""
    return LlmEvalResult(error="API 调用失败: timeout")


# ───────── 红线触发 → 不建议 ─────────


def test_red_flag_rejects() -> None:
    verdict = merge_scores(_red_flag_hard_verdict(), None, passing_score=60)
    assert verdict.final_verdict == "不建议"
    assert verdict.hard_rule_reject is True
    assert "红线" in verdict.reason


def test_red_flag_skips_llm() -> None:
    """红线触发时即使传入 LLM 结果也应返回不建议."""
    verdict = merge_scores(_red_flag_hard_verdict(), _high_score_llm(), passing_score=60)
    assert verdict.final_verdict == "不建议"
    assert verdict.llm_score is None


# ───────── 硬规则不通过（非红线）→ 不建议 ─────────


def test_hard_fail_rejects() -> None:
    verdict = merge_scores(_fail_hard_verdict(), _high_score_llm(), passing_score=60)
    assert verdict.final_verdict == "不建议"
    assert verdict.hard_rule_passed is False


# ───────── 硬规则通过 + LLM 高分 → 推荐沟通 ─────────


def test_high_score_recommends() -> None:
    # passing_score=60, recommend_threshold=60*1.33=79.8, score=85
    verdict = merge_scores(_passing_hard_verdict(), _high_score_llm(), passing_score=60)
    assert verdict.final_verdict == "推荐沟通"
    assert verdict.llm_score == 85.0
    assert len(verdict.highlights) > 0


# ───────── 硬规则通过 + LLM 中等 → 可以看看 ─────────


def test_mid_score_maybe() -> None:
    # passing_score=60, recommend_threshold=79.8, score=65
    verdict = merge_scores(_passing_hard_verdict(), _mid_score_llm(), passing_score=60)
    assert verdict.final_verdict == "可以看看"
    assert verdict.llm_score == 65.0


# ───────── 硬规则通过 + LLM 低分 → 不建议 ─────────


def test_low_score_rejects() -> None:
    # passing_score=60, score=40
    verdict = merge_scores(_passing_hard_verdict(), _low_score_llm(), passing_score=60)
    assert verdict.final_verdict == "不建议"


# ───────── LLM 不可用 → 降级为"可以看看" ─────────


def test_llm_none_degrades() -> None:
    verdict = merge_scores(_passing_hard_verdict(), None, passing_score=60)
    assert verdict.final_verdict == "可以看看"
    assert "降级" in verdict.reason


def test_llm_error_degrades() -> None:
    verdict = merge_scores(_passing_hard_verdict(), _error_llm(), passing_score=60)
    assert verdict.final_verdict == "可以看看"
    assert "降级" in verdict.reason


# ───────── 风险和亮点收集 ─────────


def test_risks_collected() -> None:
    verdict = merge_scores(_passing_hard_verdict(), _mid_score_llm(), passing_score=60)
    assert any("换工作频繁" in r for r in verdict.risks)


def test_whitelist_hits_in_highlights() -> None:
    verdict = merge_scores(_passing_hard_verdict(), _high_score_llm(), passing_score=60)
    assert any("餐饮" in h for h in verdict.highlights)
