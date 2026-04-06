"""硬规则引擎 — 基于岗位画像配置对候选人做硬性条件过滤."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.c2_scorer.profile_loader import JobProfile
from src.common.logger import get_logger

logger = get_logger(__name__)

# 学历等级映射（低 → 高）
_EDUCATION_RANK: dict[str, int] = {
    "不限": 0,
    "小学": 1,
    "初中": 2,
    "中专": 3,
    "高中": 4,
    "大专": 5,
    "本科": 6,
}


@dataclass
class CandidateInfo:
    """候选人结构化信息，由 C1 解析后传入硬规则引擎.

    所有字段均为 Optional，缺失时对应规则标记为 skipped。
    """

    age: Optional[int] = None
    education: Optional[str] = None
    expected_salary: Optional[int] = None
    work_experience_years: Optional[float] = None
    job_count_last_year: Optional[int] = None
    resume_text: Optional[str] = None


@dataclass
class RuleResult:
    """单条规则的判断结果."""

    rule_name: str
    passed: bool | None  # True=通过, False=不通过, None=跳过（字段缺失）
    detail: str = ""
    is_red_flag: bool = False


@dataclass
class HardRuleVerdict:
    """硬规则引擎整体判断结果."""

    passed: bool  # 所有规则都通过（或跳过）
    is_reject: bool  # 触发红线，直接"不建议"
    results: list[RuleResult] = field(default_factory=list)
    whitelist_hits: list[str] = field(default_factory=list)
    blacklist_hits: list[str] = field(default_factory=list)


def evaluate_hard_rules(
    candidate: CandidateInfo,
    profile: JobProfile,
) -> HardRuleVerdict:
    """对候选人执行岗位画像中的全部硬规则检查."""
    results: list[RuleResult] = []

    results.append(_check_age(candidate, profile))
    results.append(_check_education(candidate, profile))
    results.append(_check_salary(candidate, profile))
    results.append(_check_experience(candidate, profile))
    results.append(_check_job_hopping(candidate, profile))

    wl_hits, bl_hits = _check_keywords(candidate, profile)
    kw_result = _keyword_rule_result(wl_hits, bl_hits)
    results.append(kw_result)

    is_reject = any(r.is_red_flag and r.passed is False for r in results)
    passed = not any(r.passed is False for r in results)

    failed_rules = [r.rule_name for r in results if r.passed is False]
    skipped_rules = [r.rule_name for r in results if r.passed is None]
    logger.info(
        "hard_rules_evaluated",
        passed=passed,
        is_reject=is_reject,
        failed=failed_rules,
        skipped=skipped_rules,
        whitelist_hits=wl_hits,
        blacklist_hits=bl_hits,
    )

    return HardRuleVerdict(
        passed=passed,
        is_reject=is_reject,
        results=results,
        whitelist_hits=wl_hits,
        blacklist_hits=bl_hits,
    )


# ───────── 各规则实现 ─────────


def _check_age(candidate: CandidateInfo, profile: JobProfile) -> RuleResult:
    if candidate.age is None:
        return RuleResult(rule_name="age_range", passed=None, detail="年龄信息缺失")

    ar = profile.hard_rules.age_range
    if ar.min <= candidate.age <= ar.max:
        return RuleResult(
            rule_name="age_range",
            passed=True,
            detail=f"年龄 {candidate.age} 在 [{ar.min}, {ar.max}] 范围内",
        )

    # 弹性上限：有 flexible_max 且年龄在 (max, flexible_max] 之间
    if ar.flexible_max and ar.max < candidate.age <= ar.flexible_max:
        return RuleResult(
            rule_name="age_range",
            passed=True,
            detail=f"年龄 {candidate.age} 超出标准上限 {ar.max}，但在弹性上限 {ar.flexible_max} 内",
        )

    return RuleResult(
        rule_name="age_range",
        passed=False,
        is_red_flag=True,
        detail=f"年龄 {candidate.age} 不在 [{ar.min}, {ar.max}] 范围内",
    )


def _check_education(candidate: CandidateInfo, profile: JobProfile) -> RuleResult:
    if candidate.education is None:
        return RuleResult(rule_name="education_min", passed=None, detail="学历信息缺失")

    required = profile.hard_rules.education_min
    if required == "不限":
        return RuleResult(
            rule_name="education_min",
            passed=True,
            detail=f"岗位学历要求「不限」，候选人学历「{candidate.education}」",
        )

    req_rank = _EDUCATION_RANK.get(required, 0)
    cand_rank = _EDUCATION_RANK.get(candidate.education, -1)

    if cand_rank == -1:
        return RuleResult(
            rule_name="education_min",
            passed=None,
            detail=f"候选人学历「{candidate.education}」无法识别",
        )

    if cand_rank >= req_rank:
        return RuleResult(
            rule_name="education_min",
            passed=True,
            detail=f"学历「{candidate.education}」≥ 要求「{required}」",
        )

    return RuleResult(
        rule_name="education_min",
        passed=False,
        is_red_flag=True,
        detail=f"学历「{candidate.education}」低于要求「{required}」",
    )


def _check_salary(candidate: CandidateInfo, profile: JobProfile) -> RuleResult:
    if candidate.expected_salary is None:
        return RuleResult(
            rule_name="salary_range", passed=None, detail="期望薪资信息缺失"
        )

    sr = profile.hard_rules.salary_range
    # 候选人期望薪资不应远超岗位转正最高薪资（超过 1.5 倍视为不匹配）
    upper_limit = int(sr.regular_max * 1.5)
    if candidate.expected_salary > upper_limit:
        return RuleResult(
            rule_name="salary_range",
            passed=False,
            detail=f"期望薪资 {candidate.expected_salary} 远超岗位上限 {sr.regular_max}（阈值 {upper_limit}）",
        )

    return RuleResult(
        rule_name="salary_range",
        passed=True,
        detail=f"期望薪资 {candidate.expected_salary} 在可接受范围内（岗位 {sr.probation_min}-{sr.regular_max}）",
    )


def _check_experience(candidate: CandidateInfo, profile: JobProfile) -> RuleResult:
    hr = profile.hard_rules
    if not hr.experience_required:
        return RuleResult(
            rule_name="experience", passed=True, detail="岗位不强制要求工作经验"
        )

    if candidate.work_experience_years is None:
        return RuleResult(
            rule_name="experience", passed=None, detail="工作经验信息缺失"
        )

    min_years = hr.experience_min_years or 0
    if candidate.work_experience_years >= min_years:
        return RuleResult(
            rule_name="experience",
            passed=True,
            detail=f"工作经验 {candidate.work_experience_years} 年 ≥ 要求 {min_years} 年",
        )

    return RuleResult(
        rule_name="experience",
        passed=False,
        detail=f"工作经验 {candidate.work_experience_years} 年 < 要求 {min_years} 年",
    )


def _check_job_hopping(candidate: CandidateInfo, profile: JobProfile) -> RuleResult:
    """红线规则：近一年内 3 份及以上工作 → 直接不建议."""
    if candidate.job_count_last_year is None:
        return RuleResult(
            rule_name="job_hopping", passed=None, detail="近一年工作数信息缺失"
        )

    if candidate.job_count_last_year >= 3:
        return RuleResult(
            rule_name="job_hopping",
            passed=False,
            is_red_flag=True,
            detail=f"近一年 {candidate.job_count_last_year} 份工作，频繁跳槽",
        )

    return RuleResult(
        rule_name="job_hopping",
        passed=True,
        detail=f"近一年 {candidate.job_count_last_year} 份工作，正常",
    )


def _check_keywords(
    candidate: CandidateInfo, profile: JobProfile
) -> tuple[list[str], list[str]]:
    """行业关键词白名单/黑名单匹配，返回 (whitelist_hits, blacklist_hits)."""
    if not candidate.resume_text:
        return [], []

    text = candidate.resume_text
    wl_hits = [kw for kw in profile.industry_keywords.whitelist if kw in text]
    bl_hits = [kw for kw in profile.industry_keywords.blacklist if kw in text]
    return wl_hits, bl_hits


def _keyword_rule_result(
    wl_hits: list[str], bl_hits: list[str]
) -> RuleResult:
    if bl_hits:
        return RuleResult(
            rule_name="industry_keywords",
            passed=False,
            detail=f"命中黑名单关键词: {', '.join(bl_hits)}",
        )
    if wl_hits:
        return RuleResult(
            rule_name="industry_keywords",
            passed=True,
            detail=f"命中白名单关键词: {', '.join(wl_hits)}",
        )
    return RuleResult(
        rule_name="industry_keywords",
        passed=None,
        detail="未命中任何行业关键词",
    )
