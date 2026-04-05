"""Tests for c2_scorer.hard_rules — 硬规则引擎."""

import pytest

from src.c2_scorer.hard_rules import (
    CandidateInfo,
    HardRuleVerdict,
    RuleResult,
    evaluate_hard_rules,
)
from src.c2_scorer.profile_loader import load_profile

_PROFILES_DIR = __import__("pathlib").Path(__file__).resolve().parents[2] / "config" / "job_profiles"


@pytest.fixture()
def mian_dian_shi_profile():
    return load_profile("mian_dian_shi", _PROFILES_DIR)


@pytest.fixture()
def wai_pin_chu_bei_profile():
    return load_profile("wai_pin_chu_bei", _PROFILES_DIR)


@pytest.fixture()
def can_yin_xue_tu_profile():
    """餐饮学徒 max=35, flexible_max=45."""
    return load_profile("can_yin_xue_tu", _PROFILES_DIR)


@pytest.fixture()
def good_candidate() -> CandidateInfo:
    """一个完全符合面点师要求的候选人."""
    return CandidateInfo(
        age=28,
        education="高中",
        expected_salary=5000,
        work_experience_years=2.0,
        job_count_last_year=1,
        resume_text="之前在早餐店做过面点，有包子馒头制作经验",
    )


# ───────── 完整通过 ─────────


def test_good_candidate_passes(mian_dian_shi_profile, good_candidate) -> None:
    verdict = evaluate_hard_rules(good_candidate, mian_dian_shi_profile)
    assert verdict.passed is True
    assert verdict.is_reject is False
    assert len(verdict.whitelist_hits) > 0


# ───────── 红线规则：跳槽频率 ─────────


def test_job_hopping_red_flag(mian_dian_shi_profile) -> None:
    """近一年 3 份工作 → 红线，直接不建议."""
    candidate = CandidateInfo(age=25, job_count_last_year=3)
    verdict = evaluate_hard_rules(candidate, mian_dian_shi_profile)
    assert verdict.is_reject is True
    hopping = _find_rule(verdict, "job_hopping")
    assert hopping.passed is False
    assert hopping.is_red_flag is True


def test_job_hopping_boundary_ok(mian_dian_shi_profile) -> None:
    """近一年 2 份工作 → 正常."""
    candidate = CandidateInfo(age=25, job_count_last_year=2)
    verdict = evaluate_hard_rules(candidate, mian_dian_shi_profile)
    hopping = _find_rule(verdict, "job_hopping")
    assert hopping.passed is True


# ───────── 年龄范围 ─────────


def test_age_in_range(mian_dian_shi_profile) -> None:
    """年龄 20-40 内 → 通过."""
    candidate = CandidateInfo(age=20)
    verdict = evaluate_hard_rules(candidate, mian_dian_shi_profile)
    assert _find_rule(verdict, "age_range").passed is True


def test_age_at_max_boundary(mian_dian_shi_profile) -> None:
    """年龄恰好等于 max → 通过."""
    candidate = CandidateInfo(age=40)
    assert _find_rule(
        evaluate_hard_rules(candidate, mian_dian_shi_profile), "age_range"
    ).passed is True


def test_age_over_max(mian_dian_shi_profile) -> None:
    """年龄超过 max（无 flexible_max）→ 红线."""
    candidate = CandidateInfo(age=41)
    result = _find_rule(
        evaluate_hard_rules(candidate, mian_dian_shi_profile), "age_range"
    )
    assert result.passed is False
    assert result.is_red_flag is True


def test_age_under_min(mian_dian_shi_profile) -> None:
    """年龄低于 min → 红线."""
    candidate = CandidateInfo(age=19)
    result = _find_rule(
        evaluate_hard_rules(candidate, mian_dian_shi_profile), "age_range"
    )
    assert result.passed is False
    assert result.is_red_flag is True


def test_age_flexible_max_pass(can_yin_xue_tu_profile) -> None:
    """餐饮学徒 max=40, flexible_max=45，年龄 42 → 弹性通过."""
    candidate = CandidateInfo(age=42)
    result = _find_rule(
        evaluate_hard_rules(candidate, can_yin_xue_tu_profile), "age_range"
    )
    assert result.passed is True
    assert "弹性" in result.detail


def test_age_over_flexible_max(can_yin_xue_tu_profile) -> None:
    """餐饮学徒 flexible_max=45，年龄 46 → 不通过."""
    candidate = CandidateInfo(age=46)
    result = _find_rule(
        evaluate_hard_rules(candidate, can_yin_xue_tu_profile), "age_range"
    )
    assert result.passed is False


# ───────── 学历 ─────────


def test_education_no_requirement(mian_dian_shi_profile) -> None:
    """面点师学历要求「不限」→ 任何学历都通过."""
    candidate = CandidateInfo(education="小学")
    assert _find_rule(
        evaluate_hard_rules(candidate, mian_dian_shi_profile), "education_min"
    ).passed is True


def test_education_meets_requirement(wai_pin_chu_bei_profile) -> None:
    """外聘储备要求初中，候选人高中 → 通过."""
    candidate = CandidateInfo(education="高中")
    assert _find_rule(
        evaluate_hard_rules(candidate, wai_pin_chu_bei_profile), "education_min"
    ).passed is True


def test_education_below_requirement(wai_pin_chu_bei_profile) -> None:
    """外聘储备要求初中，候选人小学 → 红线."""
    candidate = CandidateInfo(education="小学")
    result = _find_rule(
        evaluate_hard_rules(candidate, wai_pin_chu_bei_profile), "education_min"
    )
    assert result.passed is False
    assert result.is_red_flag is True


def test_education_exact_boundary(wai_pin_chu_bei_profile) -> None:
    """恰好等于最低学历 → 通过."""
    candidate = CandidateInfo(education="初中")
    assert _find_rule(
        evaluate_hard_rules(candidate, wai_pin_chu_bei_profile), "education_min"
    ).passed is True


def test_education_unknown(wai_pin_chu_bei_profile) -> None:
    """无法识别的学历 → 跳过."""
    candidate = CandidateInfo(education="博士后")
    assert _find_rule(
        evaluate_hard_rules(candidate, wai_pin_chu_bei_profile), "education_min"
    ).passed is None


# ───────── 薪资 ─────────


def test_salary_within_range(mian_dian_shi_profile) -> None:
    """期望薪资在岗位范围内 → 通过."""
    candidate = CandidateInfo(expected_salary=5000)
    assert _find_rule(
        evaluate_hard_rules(candidate, mian_dian_shi_profile), "salary_range"
    ).passed is True


def test_salary_far_exceeds(mian_dian_shi_profile) -> None:
    """期望薪资远超上限 1.5 倍 → 不通过."""
    # 面点师 regular_max=6000, 1.5x=9000
    candidate = CandidateInfo(expected_salary=10000)
    assert _find_rule(
        evaluate_hard_rules(candidate, mian_dian_shi_profile), "salary_range"
    ).passed is False


def test_salary_at_threshold(mian_dian_shi_profile) -> None:
    """期望薪资恰好等于 1.5 倍上限 → 通过."""
    candidate = CandidateInfo(expected_salary=9000)
    assert _find_rule(
        evaluate_hard_rules(candidate, mian_dian_shi_profile), "salary_range"
    ).passed is True


# ───────── 工作经验 ─────────


def test_experience_not_required(mian_dian_shi_profile) -> None:
    """面点师不强制要求经验 → 直接通过."""
    candidate = CandidateInfo()
    assert _find_rule(
        evaluate_hard_rules(candidate, mian_dian_shi_profile), "experience"
    ).passed is True


def test_experience_required_and_met(wai_pin_chu_bei_profile) -> None:
    """外聘储备要求 1 年经验，候选人 2 年 → 通过."""
    candidate = CandidateInfo(work_experience_years=2.0)
    assert _find_rule(
        evaluate_hard_rules(candidate, wai_pin_chu_bei_profile), "experience"
    ).passed is True


def test_experience_required_not_met(wai_pin_chu_bei_profile) -> None:
    """外聘储备要求 1 年经验，候选人 0.5 年 → 不通过."""
    candidate = CandidateInfo(work_experience_years=0.5)
    assert _find_rule(
        evaluate_hard_rules(candidate, wai_pin_chu_bei_profile), "experience"
    ).passed is False


def test_experience_required_missing(wai_pin_chu_bei_profile) -> None:
    """要求经验但候选人信息缺失 → 跳过."""
    candidate = CandidateInfo()
    assert _find_rule(
        evaluate_hard_rules(candidate, wai_pin_chu_bei_profile), "experience"
    ).passed is None


# ───────── 行业关键词 ─────────


def test_keywords_whitelist_hit(mian_dian_shi_profile) -> None:
    """简历包含白名单关键词 → 通过 + hits 记录."""
    candidate = CandidateInfo(resume_text="曾在快餐店负责早餐面点")
    verdict = evaluate_hard_rules(candidate, mian_dian_shi_profile)
    assert len(verdict.whitelist_hits) > 0
    assert "面点" in verdict.whitelist_hits


def test_keywords_blacklist_hit(mian_dian_shi_profile) -> None:
    """简历包含黑名单关键词 → 不通过."""
    candidate = CandidateInfo(resume_text="之前在KTV做服务员，有夜班经验")
    verdict = evaluate_hard_rules(candidate, mian_dian_shi_profile)
    assert len(verdict.blacklist_hits) > 0
    kw_result = _find_rule(verdict, "industry_keywords")
    assert kw_result.passed is False


def test_keywords_no_match(mian_dian_shi_profile) -> None:
    """简历无任何关键词命中 → 跳过."""
    candidate = CandidateInfo(resume_text="做过外贸销售")
    verdict = evaluate_hard_rules(candidate, mian_dian_shi_profile)
    assert _find_rule(verdict, "industry_keywords").passed is None


def test_keywords_no_resume(mian_dian_shi_profile) -> None:
    """无简历文本 → 跳过."""
    candidate = CandidateInfo()
    verdict = evaluate_hard_rules(candidate, mian_dian_shi_profile)
    assert _find_rule(verdict, "industry_keywords").passed is None


# ───────── 字段缺失时规则跳过 ─────────


def test_all_fields_missing_no_crash(mian_dian_shi_profile) -> None:
    """所有字段为 None 时引擎不崩溃，规则标记为 skipped."""
    candidate = CandidateInfo()
    verdict = evaluate_hard_rules(candidate, mian_dian_shi_profile)
    assert isinstance(verdict, HardRuleVerdict)
    # 面点师不要求经验，所以 experience 通过；其余大多 skipped
    for r in verdict.results:
        assert isinstance(r, RuleResult)


# ───────── helpers ─────────


def _find_rule(verdict: HardRuleVerdict, rule_name: str) -> RuleResult:
    for r in verdict.results:
        if r.rule_name == rule_name:
            return r
    raise ValueError(f"Rule {rule_name!r} not found in verdict")
