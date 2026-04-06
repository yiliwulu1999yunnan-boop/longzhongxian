"""判断快照持久化 — 将评分结果存入 scoring_snapshots 表."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.c2_scorer.hard_rules import HardRuleVerdict
from src.c2_scorer.llm_scorer import LlmEvalResult
from src.c2_scorer.score_merger import MergedVerdict
from src.common.logger import get_logger
from src.common.models import ScoringSnapshot

logger = get_logger(__name__)


async def save_snapshot(
    session: AsyncSession,
    *,
    candidate_id: int,
    hard_verdict: HardRuleVerdict,
    llm_result: Optional[LlmEvalResult],
    merged: MergedVerdict,
    job_profile_version: str,
) -> ScoringSnapshot:
    """存储完整的评分快照到数据库.

    Args:
        session: SQLAlchemy 异步 session.
        candidate_id: 候选人 ID.
        hard_verdict: 硬规则引擎输出.
        llm_result: LLM 评估输出（可为 None）.
        merged: 合并后的最终判断.
        job_profile_version: 岗位画像配置版本标识.

    Returns:
        创建的 ScoringSnapshot ORM 对象.
    """
    hard_rule_data = _serialize_hard_verdict(hard_verdict)
    llm_data = _serialize_llm_result(llm_result)

    snapshot = ScoringSnapshot(
        candidate_id=candidate_id,
        hard_rule_results=hard_rule_data,
        llm_raw_output=llm_data,
        job_profile_version=job_profile_version,
        final_verdict=merged.final_verdict,
    )
    session.add(snapshot)
    await session.flush()
    logger.info(
        "snapshot_saved",
        candidate_id=candidate_id,
        verdict=merged.final_verdict,
        snapshot_id=snapshot.id,
    )
    return snapshot


def _serialize_hard_verdict(verdict: HardRuleVerdict) -> dict[str, Any]:
    """将 HardRuleVerdict 序列化为可存储的 JSON 字典."""
    return {
        "passed": verdict.passed,
        "is_reject": verdict.is_reject,
        "results": [asdict(r) for r in verdict.results],
        "whitelist_hits": verdict.whitelist_hits,
        "blacklist_hits": verdict.blacklist_hits,
    }


def _serialize_llm_result(result: Optional[LlmEvalResult]) -> Optional[dict[str, Any]]:
    """将 LlmEvalResult 序列化为可存储的 JSON 字典."""
    if result is None:
        return None
    return {
        "dimension_scores": [asdict(d) for d in result.dimension_scores],
        "weighted_total": result.weighted_total,
        "verdict": result.verdict,
        "risks": result.risks,
        "highlights": result.highlights,
        "raw_output": result.raw_output,
        "error": result.error,
    }
