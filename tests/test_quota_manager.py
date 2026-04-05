"""Tests for c4_contact/quota_manager — 配额管理."""

from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.c4_contact.quota_manager import (
    DAILY_QUOTA,
    QuotaExceededError,
    check_quota,
    get_remaining_quota,
    get_today_consumed,
    record_consumption,
)
from src.common.config import Settings
from src.common.db import get_engine, get_session_factory
from src.common.models import Base, OperationLog


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


# ───────── 配额查询 ─────────


@pytest.mark.asyncio()
async def test_fresh_account_full_quota(db_session: AsyncSession) -> None:
    """新账号无消耗记录，配额充足."""
    consumed = await get_today_consumed(db_session, "boss_1")
    assert consumed == 0

    remaining = await get_remaining_quota(db_session, "boss_1")
    assert remaining == DAILY_QUOTA


@pytest.mark.asyncio()
async def test_consumed_reduces_remaining(db_session: AsyncSession) -> None:
    """消耗记录减少剩余配额."""
    await record_consumption(db_session, "boss_1", None, "success", quota_consumed=3)
    await db_session.flush()

    remaining = await get_remaining_quota(db_session, "boss_1")
    assert remaining == DAILY_QUOTA - 3


# ───────── 配额检查 ─────────


@pytest.mark.asyncio()
async def test_check_quota_sufficient(db_session: AsyncSession) -> None:
    """配额充足时允许执行."""
    remaining = await check_quota(db_session, "boss_1", required=5)
    assert remaining == DAILY_QUOTA


@pytest.mark.asyncio()
async def test_check_quota_insufficient(db_session: AsyncSession) -> None:
    """配额不足时拒绝并返回提示."""
    # 先消耗 48 个
    for _ in range(48):
        await record_consumption(db_session, "boss_1", None, "success")
    await db_session.flush()

    # 还剩 2，请求 5 应该拒绝
    with pytest.raises(QuotaExceededError, match="剩余 2.*需要 5"):
        await check_quota(db_session, "boss_1", required=5)


@pytest.mark.asyncio()
async def test_check_quota_exactly_enough(db_session: AsyncSession) -> None:
    """配额刚好够时允许执行."""
    for _ in range(49):
        await record_consumption(db_session, "boss_1", None, "success")
    await db_session.flush()

    remaining = await check_quota(db_session, "boss_1", required=1)
    assert remaining == 1


# ───────── 跨日重置 ─────────


@pytest.mark.asyncio()
async def test_cross_day_quota_resets(db_session: AsyncSession) -> None:
    """跨日配额自动重置：昨天的消耗不影响今天."""
    yesterday = date(2026, 4, 4)
    today = date(2026, 4, 5)

    # 昨天消耗 30
    for _ in range(30):
        log = OperationLog(
            op_type="greeting",
            boss_account_id="boss_1",
            result="success",
            quota_consumed=1,
        )
        log.created_at = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
        db_session.add(log)
    await db_session.flush()

    # 今天应该是满配额
    consumed_today = await get_today_consumed(db_session, "boss_1", today=today)
    assert consumed_today == 0

    remaining_today = await get_remaining_quota(db_session, "boss_1", today=today)
    assert remaining_today == DAILY_QUOTA

    # 昨天应该是 30
    consumed_yesterday = await get_today_consumed(
        db_session, "boss_1", today=yesterday
    )
    assert consumed_yesterday == 30


# ───────── 记录消耗 ─────────


@pytest.mark.asyncio()
async def test_record_consumption_creates_log(db_session: AsyncSession) -> None:
    """记录消耗创建 OperationLog."""
    log = await record_consumption(
        db_session, "boss_1", 42, "success", detail={"msg": "ok"}
    )
    assert log.op_type == "greeting"
    assert log.boss_account_id == "boss_1"
    assert log.candidate_id == 42
    assert log.result == "success"
    assert log.quota_consumed == 1
    assert log.detail == {"msg": "ok"}


@pytest.mark.asyncio()
async def test_record_failed_zero_consumed(db_session: AsyncSession) -> None:
    """失败时 quota_consumed=0 不消耗配额."""
    await record_consumption(
        db_session, "boss_1", None, "failed", quota_consumed=0
    )
    await db_session.flush()

    remaining = await get_remaining_quota(db_session, "boss_1")
    assert remaining == DAILY_QUOTA


# ───────── 不同账号隔离 ─────────


@pytest.mark.asyncio()
async def test_different_accounts_isolated(db_session: AsyncSession) -> None:
    """不同 Boss 账号的配额互相隔离."""
    await record_consumption(db_session, "boss_1", None, "success", quota_consumed=10)
    await db_session.flush()

    remaining_1 = await get_remaining_quota(db_session, "boss_1")
    remaining_2 = await get_remaining_quota(db_session, "boss_2")

    assert remaining_1 == DAILY_QUOTA - 10
    assert remaining_2 == DAILY_QUOTA
