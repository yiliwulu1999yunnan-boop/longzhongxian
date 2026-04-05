"""C4 模块集成测试 — 批量打招呼流程端到端验证（全 mock）."""

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.c4_contact.greeting_sender import GreetingOutcome, GreetingResult
from src.c4_contact.pipeline import GreetingTarget, run_c4_pipeline
from src.c4_contact.quota_manager import DAILY_QUOTA, record_consumption
from src.common.config import Settings
from src.common.db import get_engine, get_session_factory
from src.common.models import Base


def _make_targets(count: int) -> list[GreetingTarget]:
    """生成测试用打招呼目标列表."""
    return [
        GreetingTarget(
            candidate_id=100 + i,
            encrypt_geek_id=f"geek_{i}",
            detail_url=f"https://www.zhipin.com/geek/{i}",
            greeting_message="您好，我们是笼中仙",
            name=f"候选人{i}",
        )
        for i in range(count)
    ]


def _mock_page(outcomes: list[GreetingResult]) -> AsyncMock:
    """创建 mock page，按顺序返回指定结果."""
    page = AsyncMock()
    return page


def _mock_channel() -> AsyncMock:
    """创建 mock PushChannel."""
    channel = AsyncMock()
    channel.send_text = AsyncMock()
    channel.send_markdown = AsyncMock()
    return channel


@pytest_asyncio.fixture()
async def db_session():
    """内存 SQLite 数据库 session."""
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:", _env_file=None)
    engine = get_engine(settings)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = get_session_factory(engine)
    async with session_factory() as session:
        yield session

    await engine.dispose()


# ───────── 批量执行结果正确汇总并推送 ─────────


@pytest.mark.asyncio()
async def test_full_pipeline_all_success(db_session: AsyncSession) -> None:
    """全部成功：3 个候选人都发送成功，结果推送给店长."""
    targets = _make_targets(3)
    channel = _mock_channel()
    page = AsyncMock()

    # mock send_greeting 全部成功
    success_outcomes = [
        GreetingOutcome(encrypt_geek_id=f"geek_{i}", result=GreetingResult.SUCCESS)
        for i in range(3)
    ]
    with pytest.MonkeyPatch.context() as mp:
        call_idx = {"i": 0}

        async def fake_send(p, *, detail_url, encrypt_geek_id, greeting_message):  # noqa: ANN001, ANN003
            idx = call_idx["i"]
            call_idx["i"] += 1
            return success_outcomes[idx]

        mp.setattr("src.c4_contact.pipeline.send_greeting", fake_send)

        result = await run_c4_pipeline(
            page, db_session, channel,
            targets=targets,
            boss_account_id="boss_1",
            wechat_userid="user_store_1",
        )

    assert result.success_count == 3
    assert result.failed_count == 0
    assert not result.quota_exhausted
    assert result.remaining_quota == DAILY_QUOTA - 3

    # 验证推送通知
    channel.send_text.assert_awaited_once()
    msg = channel.send_text.call_args[0][1]
    assert "成功 3" in msg


@pytest.mark.asyncio()
async def test_pipeline_partial_failure(db_session: AsyncSession) -> None:
    """部分失败：2 成功 1 失败，结果正确汇总."""
    targets = _make_targets(3)
    channel = _mock_channel()
    page = AsyncMock()

    outcomes = [
        GreetingOutcome(encrypt_geek_id="geek_0", result=GreetingResult.SUCCESS),
        GreetingOutcome(
            encrypt_geek_id="geek_1", result=GreetingResult.PAGE_ERROR, detail="err"
        ),
        GreetingOutcome(encrypt_geek_id="geek_2", result=GreetingResult.SUCCESS),
    ]
    with pytest.MonkeyPatch.context() as mp:
        call_idx = {"i": 0}

        async def fake_send(p, *, detail_url, encrypt_geek_id, greeting_message):  # noqa: ANN001, ANN003
            idx = call_idx["i"]
            call_idx["i"] += 1
            return outcomes[idx]

        mp.setattr("src.c4_contact.pipeline.send_greeting", fake_send)

        result = await run_c4_pipeline(
            page, db_session, channel,
            targets=targets,
            boss_account_id="boss_1",
            wechat_userid="user_store_1",
        )

    assert result.success_count == 2
    assert result.failed_count == 1
    msg = channel.send_text.call_args[0][1]
    assert "成功 2" in msg
    assert "失败 1" in msg


@pytest.mark.asyncio()
async def test_pipeline_quota_exhausted_mid_batch(db_session: AsyncSession) -> None:
    """批量执行中途配额耗尽，停止后续执行."""
    targets = _make_targets(3)
    channel = _mock_channel()
    page = AsyncMock()

    outcomes = [
        GreetingOutcome(encrypt_geek_id="geek_0", result=GreetingResult.SUCCESS),
        GreetingOutcome(
            encrypt_geek_id="geek_1", result=GreetingResult.QUOTA_EXHAUSTED
        ),
    ]
    with pytest.MonkeyPatch.context() as mp:
        call_idx = {"i": 0}

        async def fake_send(p, *, detail_url, encrypt_geek_id, greeting_message):  # noqa: ANN001, ANN003
            idx = call_idx["i"]
            call_idx["i"] += 1
            return outcomes[idx]

        mp.setattr("src.c4_contact.pipeline.send_greeting", fake_send)

        result = await run_c4_pipeline(
            page, db_session, channel,
            targets=targets,
            boss_account_id="boss_1",
            wechat_userid="user_store_1",
        )

    assert result.success_count == 1
    assert result.quota_exhausted
    # 第三个候选人不应被执行（break 后停止）
    assert len(result.outcomes) == 2


@pytest.mark.asyncio()
async def test_pipeline_no_targets(db_session: AsyncSession) -> None:
    """空目标列表，直接推送通知."""
    channel = _mock_channel()
    page = AsyncMock()

    result = await run_c4_pipeline(
        page, db_session, channel,
        targets=[],
        boss_account_id="boss_1",
        wechat_userid="user_store_1",
    )

    assert result.success_count == 0
    assert result.failed_count == 0
    channel.send_text.assert_awaited_once()


@pytest.mark.asyncio()
async def test_pipeline_pre_check_quota_exhausted(db_session: AsyncSession) -> None:
    """执行前配额已为零，直接拒绝."""
    # 先消耗完配额
    for _ in range(DAILY_QUOTA):
        await record_consumption(db_session, "boss_1", None, "success")
    await db_session.flush()

    targets = _make_targets(3)
    channel = _mock_channel()
    page = AsyncMock()

    result = await run_c4_pipeline(
        page, db_session, channel,
        targets=targets,
        boss_account_id="boss_1",
        wechat_userid="user_store_1",
    )

    assert result.quota_exhausted
    assert result.success_count == 0
    msg = channel.send_text.call_args[0][1]
    assert "配额已耗尽" in msg
