"""Tests for c2_scorer.snapshot_store — 判断快照持久化."""

import pytest
import pytest_asyncio
from sqlalchemy import select

from src.c2_scorer.hard_rules import HardRuleVerdict, RuleResult
from src.c2_scorer.llm_scorer import DimensionScore, LlmEvalResult
from src.c2_scorer.score_merger import MergedVerdict
from src.c2_scorer.snapshot_store import save_snapshot
from src.common.config import Settings
from src.common.db import get_engine, get_session_factory
from src.common.models import Base, Candidate, ScoringSnapshot


@pytest_asyncio.fixture()
async def db_session():
    """创建内存 SQLite 数据库并返回 session."""
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:", _env_file=None)
    engine = get_engine(settings)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = get_session_factory(engine)
    async with session_factory() as session:
        # 先创建一个候选人记录
        candidate = Candidate(encrypt_geek_id="test_geek_001")
        session.add(candidate)
        await session.flush()
        yield session, candidate.id

    await engine.dispose()


def _sample_hard_verdict() -> HardRuleVerdict:
    return HardRuleVerdict(
        passed=True,
        is_reject=False,
        results=[
            RuleResult(rule_name="age_range", passed=True, detail="年龄 25 在范围内"),
            RuleResult(rule_name="education_min", passed=True, detail="学历达标"),
        ],
        whitelist_hits=["餐饮"],
        blacklist_hits=[],
    )


def _sample_llm_result() -> LlmEvalResult:
    return LlmEvalResult(
        dimension_scores=[
            DimensionScore(name="能早起", score=80, weight=15, reason="有经验"),
        ],
        weighted_total=75.0,
        verdict="可以看看",
        risks=["稳定性一般"],
        highlights=["面点经验丰富"],
        raw_output='{"weighted_total": 75}',
    )


def _sample_merged() -> MergedVerdict:
    return MergedVerdict(
        final_verdict="可以看看",
        reason="LLM 总分 75.0",
        risks=["稳定性一般"],
        highlights=["面点经验丰富"],
        llm_score=75.0,
    )


@pytest.mark.asyncio
async def test_save_snapshot_with_llm(db_session) -> None:
    """完整快照（含 LLM 结果）存储到数据库."""
    session, candidate_id = db_session

    snapshot = await save_snapshot(
        session,
        candidate_id=candidate_id,
        hard_verdict=_sample_hard_verdict(),
        llm_result=_sample_llm_result(),
        merged=_sample_merged(),
        job_profile_version="mian_dian_shi:15-15-10-10-15-10-10-15:ps60",
    )

    assert snapshot.id is not None
    assert snapshot.candidate_id == candidate_id
    assert snapshot.final_verdict == "可以看看"
    assert snapshot.job_profile_version.startswith("mian_dian_shi")

    # 验证 JSON 字段可反序列化
    assert snapshot.hard_rule_results["passed"] is True
    assert len(snapshot.hard_rule_results["results"]) == 2
    assert snapshot.llm_raw_output["weighted_total"] == 75.0
    assert snapshot.llm_raw_output["dimension_scores"][0]["name"] == "能早起"


@pytest.mark.asyncio
async def test_save_snapshot_without_llm(db_session) -> None:
    """无 LLM 结果时（红线触发）快照存储 llm_raw_output 为 None."""
    session, candidate_id = db_session

    merged = MergedVerdict(
        final_verdict="不建议",
        reason="触发红线",
        hard_rule_passed=False,
        hard_rule_reject=True,
    )
    snapshot = await save_snapshot(
        session,
        candidate_id=candidate_id,
        hard_verdict=_sample_hard_verdict(),
        llm_result=None,
        merged=merged,
        job_profile_version="mian_dian_shi:v1",
    )

    assert snapshot.final_verdict == "不建议"
    assert snapshot.llm_raw_output is None


@pytest.mark.asyncio
async def test_snapshot_queryable(db_session) -> None:
    """存储后可通过 ORM 查询回来."""
    session, candidate_id = db_session

    await save_snapshot(
        session,
        candidate_id=candidate_id,
        hard_verdict=_sample_hard_verdict(),
        llm_result=_sample_llm_result(),
        merged=_sample_merged(),
        job_profile_version="test_v1",
    )
    await session.commit()

    result = await session.execute(
        select(ScoringSnapshot).where(ScoringSnapshot.candidate_id == candidate_id)
    )
    row = result.scalar_one()
    assert row.final_verdict == "可以看看"
    assert row.hard_rule_results["whitelist_hits"] == ["餐饮"]
