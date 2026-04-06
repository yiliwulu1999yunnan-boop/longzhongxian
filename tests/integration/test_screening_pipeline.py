"""C3.3b 筛选链路全链路集成测试 — 验证 C1→C2→C3 完整流程."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.c1_scraper.browser import BrowserManager
from src.c2_scorer.llm_scorer import LlmScorer
from src.c2_scorer.profile_loader import load_profile
from src.c3_push.channel import PushChannel
from src.common.config import Settings
from src.common.db import get_engine, get_session_factory
from src.common.models import Base, Candidate
from src.common.screening_pipeline import run_screening

_PROFILES_DIR = Path(__file__).resolve().parents[2] / "config" / "job_profiles"
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_screening_candidates() -> list[dict]:
    return json.loads(
        (_FIXTURES_DIR / "screening_candidates.json").read_text("utf-8")
    )


def _make_store_accounts_yaml(tmp_dir: Path) -> str:
    """创建临时的 store_accounts.yaml 供测试使用."""
    yaml_path = tmp_dir / "store_accounts.yaml"
    yaml_path.write_text(
        "stores:\n"
        '  - wechat_userid: "test_wechat_001"\n'
        '    store_id: "store_001"\n'
        '    store_name: "测试门店"\n'
        '    boss_account_id: "boss_test_001"\n'
        '    storage_state_path: "./storage_states/test.json"\n'
        '    job_type: "面点师"\n',
        encoding="utf-8",
    )
    return str(yaml_path)


def _make_llm_response(verdict: str, score: float) -> MagicMock:
    """创建模拟 LLM API 响应."""
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


def _make_mock_channel() -> AsyncMock:
    """创建 mock PushChannel."""
    channel = AsyncMock(spec=PushChannel)
    channel.send_text = AsyncMock()
    channel.send_markdown = AsyncMock()
    return channel


def _make_mock_browser_manager() -> AsyncMock:
    """创建 mock BrowserManager."""
    mgr = AsyncMock(spec=BrowserManager)
    mgr.storage_state_expiry_warning = False
    return mgr


@pytest_asyncio.fixture()
async def db_session():
    """内存 SQLite + 建表."""
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:", _env_file=None)
    engine = get_engine(settings)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = get_session_factory(engine)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture()
def yaml_path(tmp_path: Path) -> str:
    return _make_store_accounts_yaml(tmp_path)


# ───────── 场景 1: 正常全链路 ─────────


@pytest.mark.asyncio
async def test_full_pipeline_happy_path(db_session, yaml_path) -> None:
    """正常全链路：C1 抓取 → C2 打分 → C3 推送报告."""
    session = db_session
    profile = load_profile("mian_dian_shi", _PROFILES_DIR)
    candidates_data = _load_screening_candidates()
    channel = _make_mock_channel()

    # 构造 C1 返回的 Candidate 对象（模拟入库后的状态）
    db_candidates: list[Candidate] = []
    for item in candidates_data:
        c = Candidate(
            encrypt_geek_id=item["encryptGeekId"],
            raw_json=item,
            detail_url=item.get("detailUrl", ""),
            boss_account_id="boss_test_001",
        )
        session.add(c)
    await session.flush()
    # 重新查询获取带 id 的对象
    from sqlalchemy import select
    result = await session.execute(select(Candidate))
    db_candidates = list(result.scalars().all())

    with (
        patch("src.common.screening_pipeline.run_c1_pipeline", new_callable=AsyncMock)
            as mock_c1,
        patch("src.c2_scorer.llm_scorer.AsyncOpenAI") as mock_openai_cls,
    ):
        mock_c1.return_value = db_candidates
        # LLM 返回高分 → 推荐沟通
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = _make_llm_response(
            "推荐沟通", 85.0,
        )
        mock_openai_cls.return_value = mock_client
        scorer = LlmScorer(api_key="test", base_url="http://test")

        screening_result = await run_screening(
            browser_manager=_make_mock_browser_manager(),
            session=session,
            channel=channel,
            llm_scorer=scorer,
            profile=profile,
            boss_account_id="boss_test_001",
            yaml_path=yaml_path,
        )

    assert screening_result.candidates_scraped == 2
    assert screening_result.candidates_scored == 2
    assert screening_result.report_sent is True
    assert screening_result.error is None
    # 企微推送被调用
    channel.send_markdown.assert_awaited_once()


# ───────── 场景 2: 去重 — 同一候选人不重复打分推送 ─────────


@pytest.mark.asyncio
async def test_dedup_no_double_scoring(db_session, yaml_path) -> None:
    """同一候选人第二次运行 → C1 返回空列表 → 不重复打分推送."""
    session = db_session
    profile = load_profile("mian_dian_shi", _PROFILES_DIR)
    channel = _make_mock_channel()

    with (
        patch("src.common.screening_pipeline.run_c1_pipeline", new_callable=AsyncMock)
            as mock_c1,
        patch("src.c2_scorer.llm_scorer.AsyncOpenAI") as mock_openai_cls,
    ):
        # C1 返回空 — 候选人已经抓取过
        mock_c1.return_value = []
        mock_openai_cls.return_value = AsyncMock()
        scorer = LlmScorer(api_key="test", base_url="http://test")

        result = await run_screening(
            browser_manager=_make_mock_browser_manager(),
            session=session,
            channel=channel,
            llm_scorer=scorer,
            profile=profile,
            boss_account_id="boss_test_001",
            yaml_path=yaml_path,
        )

    assert result.candidates_scraped == 0
    assert result.candidates_scored == 0
    # 收到"无新候选人"通知
    channel.send_text.assert_awaited_once()
    call_args = channel.send_text.call_args
    assert "新候选人" in call_args[0][1]


# ───────── 场景 3: C1 失败 → 店长收到错误通知 ─────────


@pytest.mark.asyncio
async def test_c1_failure_notifies_manager(db_session, yaml_path) -> None:
    """C1 抓取异常 → 店长收到错误通知，流程中止."""
    session = db_session
    profile = load_profile("mian_dian_shi", _PROFILES_DIR)
    channel = _make_mock_channel()

    with (
        patch("src.common.screening_pipeline.run_c1_pipeline", new_callable=AsyncMock)
            as mock_c1,
        patch("src.c2_scorer.llm_scorer.AsyncOpenAI") as mock_openai_cls,
    ):
        mock_c1.side_effect = RuntimeError("浏览器连接超时")
        mock_openai_cls.return_value = AsyncMock()
        scorer = LlmScorer(api_key="test", base_url="http://test")

        result = await run_screening(
            browser_manager=_make_mock_browser_manager(),
            session=session,
            channel=channel,
            llm_scorer=scorer,
            profile=profile,
            boss_account_id="boss_test_001",
            yaml_path=yaml_path,
        )

    assert result.error is not None
    assert "C1 失败" in result.error
    assert result.candidates_scraped == 0
    assert result.report_sent is False
    # 店长收到错误通知
    channel.send_text.assert_awaited_once()
    notify_msg = channel.send_text.call_args[0][1]
    assert "失败" in notify_msg


# ───────── 场景 4: C2 LLM 异常降级 ─────────


@pytest.mark.asyncio
async def test_c2_llm_error_degrades(db_session, yaml_path) -> None:
    """LLM 调用失败 → 硬规则通过的候选人降级为'可以看看'，流程继续."""
    session = db_session
    profile = load_profile("mian_dian_shi", _PROFILES_DIR)
    candidates_data = _load_screening_candidates()
    channel = _make_mock_channel()

    # 只用第一个候选人
    item = candidates_data[0]
    c = Candidate(
        encrypt_geek_id=item["encryptGeekId"],
        raw_json=item,
        detail_url=item.get("detailUrl", ""),
        boss_account_id="boss_test_001",
    )
    session.add(c)
    await session.flush()

    from sqlalchemy import select
    result = await session.execute(select(Candidate))
    db_candidates = list(result.scalars().all())

    from openai import APITimeoutError

    with (
        patch("src.common.screening_pipeline.run_c1_pipeline", new_callable=AsyncMock)
            as mock_c1,
        patch("src.c2_scorer.llm_scorer.AsyncOpenAI") as mock_openai_cls,
    ):
        mock_c1.return_value = db_candidates
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = APITimeoutError(
            request=MagicMock(),
        )
        mock_openai_cls.return_value = mock_client
        scorer = LlmScorer(api_key="test", base_url="http://test")

        screening_result = await run_screening(
            browser_manager=_make_mock_browser_manager(),
            session=session,
            channel=channel,
            llm_scorer=scorer,
            profile=profile,
            boss_account_id="boss_test_001",
            yaml_path=yaml_path,
        )

    # LLM 失败但流程继续，候选人仍被评分（降级）
    assert screening_result.candidates_scraped == 1
    assert screening_result.candidates_scored == 1
    assert screening_result.report_sent is True
    channel.send_markdown.assert_awaited_once()
