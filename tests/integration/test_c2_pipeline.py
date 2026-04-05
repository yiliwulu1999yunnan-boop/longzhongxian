"""C2 模块集成测试 — 端到端验证完整评分链路."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.c2_scorer.hard_rules import CandidateInfo
from src.c2_scorer.llm_scorer import LlmScorer
from src.c2_scorer.pipeline import run_c2_pipeline
from src.c2_scorer.profile_loader import load_profile
from src.common.config import Settings
from src.common.db import get_engine, get_session_factory
from src.common.models import Base, Candidate

_PROFILES_DIR = Path(__file__).resolve().parents[2] / "config" / "job_profiles"
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_sample_candidates() -> list[dict]:
    return json.loads((_FIXTURES_DIR / "sample_candidates.json").read_text("utf-8"))


def _make_llm_mock_response(verdict: str, score: float) -> MagicMock:
    """创建模拟 LLM API 正常响应."""
    response_json = json.dumps(
        {
            "dimension_scores": [
                {"name": "能早起/手脚麻利", "score": 80, "reason": "可以"},
            ],
            "weighted_total": score,
            "verdict": verdict,
            "risks": ["测试风险"],
            "highlights": ["测试亮点"],
        },
        ensure_ascii=False,
    )
    mock_choice = MagicMock()
    mock_choice.message.content = response_json
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


@pytest_asyncio.fixture()
async def db_session():
    """内存 SQLite + 建表 + 预插入候选人."""
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:", _env_file=None)
    engine = get_engine(settings)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = get_session_factory(engine)
    async with session_factory() as session:
        # 为每个样本创建候选人记录
        candidates = {}
        for sample in _load_sample_candidates():
            c = Candidate(encrypt_geek_id=sample["id"])
            session.add(c)
            await session.flush()
            candidates[sample["id"]] = c.id
        yield session, candidates

    await engine.dispose()


# ───────── 端到端场景测试 ─────────


@pytest.mark.asyncio
async def test_pipeline_red_flag_skips_llm(db_session) -> None:
    """红线候选人（频繁跳槽）→ 不建议，不调用 LLM."""
    session, candidates = db_session
    sample = _load_sample_candidates()[1]  # sample_002: 跳槽红线
    profile = load_profile(sample["position_id"], _PROFILES_DIR)

    with patch("src.c2_scorer.llm_scorer.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        scorer = LlmScorer(api_key="test", base_url="http://test")

        result = await run_c2_pipeline(
            candidate_info=CandidateInfo(**sample["candidate_info"]),
            candidate_text=sample["candidate_text"],
            candidate_id=candidates[sample["id"]],
            profile=profile,
            llm_scorer=scorer,
            session=session,
        )

    assert result.merged.final_verdict == "不建议"
    assert result.hard_verdict.is_reject is True
    assert result.llm_result is None
    # LLM 不应被调用
    mock_client.chat.completions.create.assert_not_awaited()
    # 快照已存储
    assert result.snapshot is not None
    assert result.snapshot.final_verdict == "不建议"


@pytest.mark.asyncio
async def test_pipeline_education_reject(db_session) -> None:
    """学历不达标 → 不建议."""
    session, candidates = db_session
    sample = _load_sample_candidates()[2]  # sample_003: 小学 < 初中要求
    profile = load_profile(sample["position_id"], _PROFILES_DIR)

    with patch("src.c2_scorer.llm_scorer.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        scorer = LlmScorer(api_key="test", base_url="http://test")

        result = await run_c2_pipeline(
            candidate_info=CandidateInfo(**sample["candidate_info"]),
            candidate_text=sample["candidate_text"],
            candidate_id=candidates[sample["id"]],
            profile=profile,
            llm_scorer=scorer,
            session=session,
        )

    assert result.merged.final_verdict == "不建议"


@pytest.mark.asyncio
async def test_pipeline_high_score_recommends(db_session) -> None:
    """优质候选人 + LLM 高分 → 推荐沟通."""
    session, candidates = db_session
    sample = _load_sample_candidates()[0]  # sample_001: 好候选人
    profile = load_profile(sample["position_id"], _PROFILES_DIR)

    with patch("src.c2_scorer.llm_scorer.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        # 面点师 passing_score=60, recommend_threshold=79.8
        mock_client.chat.completions.create.return_value = _make_llm_mock_response(
            "推荐沟通", 85.0
        )
        mock_cls.return_value = mock_client
        scorer = LlmScorer(api_key="test", base_url="http://test")

        result = await run_c2_pipeline(
            candidate_info=CandidateInfo(**sample["candidate_info"]),
            candidate_text=sample["candidate_text"],
            candidate_id=candidates[sample["id"]],
            profile=profile,
            llm_scorer=scorer,
            session=session,
        )

    assert result.merged.final_verdict == "推荐沟通"
    assert result.llm_result is not None
    assert result.llm_result.weighted_total == 85.0
    assert result.snapshot is not None
    assert result.snapshot.llm_raw_output is not None


@pytest.mark.asyncio
async def test_pipeline_mid_score_maybe(db_session) -> None:
    """普通候选人 + LLM 中等分 → 可以看看."""
    session, candidates = db_session
    sample = _load_sample_candidates()[3]  # sample_004: 转行候选人
    profile = load_profile(sample["position_id"], _PROFILES_DIR)

    with patch("src.c2_scorer.llm_scorer.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _make_llm_mock_response(
            "可以看看", 65.0
        )
        mock_cls.return_value = mock_client
        scorer = LlmScorer(api_key="test", base_url="http://test")

        result = await run_c2_pipeline(
            candidate_info=CandidateInfo(**sample["candidate_info"]),
            candidate_text=sample["candidate_text"],
            candidate_id=candidates[sample["id"]],
            profile=profile,
            llm_scorer=scorer,
            session=session,
        )

    assert result.merged.final_verdict == "可以看看"


@pytest.mark.asyncio
async def test_pipeline_salary_reject(db_session) -> None:
    """期望薪资远超 → 不建议（硬规则不通过，但非红线）."""
    session, candidates = db_session
    sample = _load_sample_candidates()[4]  # sample_005: 薪资 12000
    profile = load_profile(sample["position_id"], _PROFILES_DIR)

    with patch("src.c2_scorer.llm_scorer.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        scorer = LlmScorer(api_key="test", base_url="http://test")

        result = await run_c2_pipeline(
            candidate_info=CandidateInfo(**sample["candidate_info"]),
            candidate_text=sample["candidate_text"],
            candidate_id=candidates[sample["id"]],
            profile=profile,
            llm_scorer=scorer,
            session=session,
        )

    assert result.merged.final_verdict == "不建议"


@pytest.mark.asyncio
async def test_pipeline_llm_error_degrades(db_session) -> None:
    """LLM 超时 → 降级为可以看看."""
    session, candidates = db_session
    sample = _load_sample_candidates()[0]  # 好候选人，但 LLM 挂了
    profile = load_profile(sample["position_id"], _PROFILES_DIR)

    from openai import APITimeoutError

    with patch("src.c2_scorer.llm_scorer.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = APITimeoutError(
            request=MagicMock()
        )
        mock_cls.return_value = mock_client
        scorer = LlmScorer(api_key="test", base_url="http://test")

        result = await run_c2_pipeline(
            candidate_info=CandidateInfo(**sample["candidate_info"]),
            candidate_text=sample["candidate_text"],
            candidate_id=candidates[sample["id"]],
            profile=profile,
            llm_scorer=scorer,
            session=session,
        )

    assert result.merged.final_verdict == "可以看看"
    assert result.llm_result is not None
    assert result.llm_result.error is not None
    assert "降级" in result.merged.reason


@pytest.mark.asyncio
async def test_pipeline_snapshot_has_profile_version(db_session) -> None:
    """快照记录包含岗位画像版本标识."""
    session, candidates = db_session
    sample = _load_sample_candidates()[1]  # 红线候选人
    profile = load_profile(sample["position_id"], _PROFILES_DIR)

    with patch("src.c2_scorer.llm_scorer.AsyncOpenAI") as mock_cls:
        mock_cls.return_value = AsyncMock()
        scorer = LlmScorer(api_key="test", base_url="http://test")

        result = await run_c2_pipeline(
            candidate_info=CandidateInfo(**sample["candidate_info"]),
            candidate_text=sample["candidate_text"],
            candidate_id=candidates[sample["id"]],
            profile=profile,
            llm_scorer=scorer,
            session=session,
        )

    assert result.snapshot is not None
    assert result.snapshot.job_profile_version == profile.config_version
    assert "mian_dian_shi" in result.snapshot.job_profile_version


# ───────── 准确率框架 ─────────


@pytest.mark.asyncio
async def test_accuracy_framework(db_session) -> None:
    """用标注样本集验证评分准确率（红线判断部分，不依赖 LLM）.

    红线/硬规则判断是确定性的，可以精确验证。
    LLM 部分因 mock 不代表真实质量，仅验证流程通畅。
    """
    session, candidates = db_session
    samples = _load_sample_candidates()

    # 硬规则可确定性判断的样本
    hard_rule_samples = [s for s in samples if s.get("reason") in (
        "频繁跳槽红线", "学历不达标", "期望薪资远超岗位范围",
    )]

    correct = 0
    for sample in hard_rule_samples:
        profile = load_profile(sample["position_id"], _PROFILES_DIR)

        with patch("src.c2_scorer.llm_scorer.AsyncOpenAI") as mock_cls:
            mock_cls.return_value = AsyncMock()
            scorer = LlmScorer(api_key="test", base_url="http://test")

            result = await run_c2_pipeline(
                candidate_info=CandidateInfo(**sample["candidate_info"]),
                candidate_text=sample["candidate_text"],
                candidate_id=candidates[sample["id"]],
                profile=profile,
                llm_scorer=scorer,
                session=session,
            )

        if result.merged.final_verdict == sample["label"]:
            correct += 1

    accuracy = correct / len(hard_rule_samples) if hard_rule_samples else 0
    assert accuracy == 1.0, (
        f"硬规则准确率 {accuracy:.0%}，期望 100%"
        f"（{correct}/{len(hard_rule_samples)}）"
    )
