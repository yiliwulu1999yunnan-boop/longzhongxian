"""C2 流程编排入口 — 候选人数据 → 硬规则 → LLM 评估 → 合并 → 快照存储."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.c2_scorer.hard_rules import CandidateInfo, HardRuleVerdict, evaluate_hard_rules
from src.c2_scorer.llm_scorer import LlmEvalResult, LlmScorer
from src.c2_scorer.score_merger import MergedVerdict, merge_scores
from src.c2_scorer.snapshot_store import save_snapshot
from src.c2_scorer.profile_loader import JobProfile
from src.common.logger import get_logger
from src.common.models import ScoringSnapshot

logger = get_logger(__name__)


class C2Result:
    """C2 流程编排的完整输出."""

    __slots__ = (
        "hard_verdict", "llm_result", "merged", "snapshot",
    )

    def __init__(
        self,
        hard_verdict: HardRuleVerdict,
        llm_result: Optional[LlmEvalResult],
        merged: MergedVerdict,
        snapshot: Optional[ScoringSnapshot],
    ) -> None:
        self.hard_verdict = hard_verdict
        self.llm_result = llm_result
        self.merged = merged
        self.snapshot = snapshot


async def run_c2_pipeline(
    candidate_info: CandidateInfo,
    candidate_text: str,
    candidate_id: int,
    profile: JobProfile,
    llm_scorer: LlmScorer,
    session: AsyncSession,
    *,
    dry_run: bool = False,
) -> C2Result:
    """执行 C2 完整评分链路.

    流程：
    1. 硬规则过滤
    2. 若硬规则触发红线 → 跳过 LLM，直接合并为"不建议"
    3. 硬规则通过 → 调用 LLM 评估
    4. 合并硬规则 + LLM 结果
    5. 存储判断快照（dry_run 跳过）

    Args:
        candidate_info: 候选人结构化信息（用于硬规则）.
        candidate_text: 候选人简历文本（用于 LLM）.
        candidate_id: 候选人数据库 ID.
        profile: 岗位画像配置.
        llm_scorer: LLM 评估器实例.
        session: 数据库 async session.
        dry_run: True 时跳过快照存储，用于风控测试.

    Returns:
        C2Result 包含各阶段输出（snapshot 字段在 dry_run 时为 None）.
    """
    logger.info("c2_pipeline_start", candidate_id=candidate_id, position=profile.position_name)

    # 1. 硬规则过滤
    hard_verdict = evaluate_hard_rules(candidate_info, profile)
    logger.info(
        "c2_hard_rules_done",
        candidate_id=candidate_id,
        passed=hard_verdict.passed,
        is_reject=hard_verdict.is_reject,
    )

    # 2. 硬规则不通过 → 跳过 LLM（红线或普通不通过都不需要 LLM）
    llm_result: Optional[LlmEvalResult] = None
    if hard_verdict.passed:
        # 3. LLM 评估
        llm_result = await llm_scorer.evaluate(profile, candidate_text)
        logger.info(
            "c2_llm_done",
            candidate_id=candidate_id,
            score=llm_result.weighted_total if llm_result else None,
            error=llm_result.error if llm_result else None,
        )
    else:
        logger.info("c2_llm_skipped", candidate_id=candidate_id, reason="hard_rules_failed")

    # 4. 合并
    merged = merge_scores(
        hard_verdict, llm_result, profile.llm_evaluation.passing_score
    )
    logger.info(
        "c2_merged",
        candidate_id=candidate_id,
        verdict=merged.final_verdict,
        reason=merged.reason,
    )

    # 5. 存储快照（dry_run 跳过）
    snapshot: Optional[ScoringSnapshot] = None
    if not dry_run:
        snapshot = await save_snapshot(
            session,
            candidate_id=candidate_id,
            hard_verdict=hard_verdict,
            llm_result=llm_result,
            merged=merged,
            job_profile_version=profile.config_version,
        )
    else:
        logger.info("c2_snapshot_skipped", candidate_id=candidate_id)
    logger.info("c2_pipeline_done", candidate_id=candidate_id, verdict=merged.final_verdict)

    return C2Result(
        hard_verdict=hard_verdict,
        llm_result=llm_result,
        merged=merged,
        snapshot=snapshot,
    )
