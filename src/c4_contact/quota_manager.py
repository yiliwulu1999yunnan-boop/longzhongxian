"""配额管理器 — 记录每个 Boss 账号的每日打招呼消耗."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logger import get_logger
from src.common.models import OperationLog

logger = get_logger(__name__)

# Boss 直聘畅聊版每日打招呼上限
DAILY_QUOTA = 50

_OP_TYPE_GREETING = "greeting"


class QuotaExceededError(Exception):
    """配额不足，拒绝执行."""


async def get_today_consumed(
    session: AsyncSession,
    boss_account_id: str,
    *,
    today: date | None = None,
) -> int:
    """查询指定 Boss 账号今日已消耗配额.

    Args:
        session: 数据库 async session.
        boss_account_id: Boss 账号 ID.
        today: 指定日期（默认当天 UTC），用于跨日重置逻辑.

    Returns:
        今日已消耗的配额数.
    """
    if today is None:
        today = datetime.now(timezone.utc).date()

    start_of_day = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    end_of_day = datetime(
        today.year, today.month, today.day, 23, 59, 59, tzinfo=timezone.utc
    )

    result = await session.execute(
        select(func.coalesce(func.sum(OperationLog.quota_consumed), 0)).where(
            OperationLog.boss_account_id == boss_account_id,
            OperationLog.op_type == _OP_TYPE_GREETING,
            OperationLog.created_at >= start_of_day,
            OperationLog.created_at <= end_of_day,
        )
    )
    return int(result.scalar_one())


async def get_remaining_quota(
    session: AsyncSession,
    boss_account_id: str,
    *,
    today: date | None = None,
) -> int:
    """查询剩余配额."""
    consumed = await get_today_consumed(session, boss_account_id, today=today)
    return max(0, DAILY_QUOTA - consumed)


async def check_quota(
    session: AsyncSession,
    boss_account_id: str,
    required: int = 1,
) -> int:
    """检查配额是否充足，返回剩余配额.

    Args:
        session: 数据库 async session.
        boss_account_id: Boss 账号 ID.
        required: 本次需要消耗的配额数.

    Returns:
        剩余配额数.

    Raises:
        QuotaExceededError: 配额不足.
    """
    remaining = await get_remaining_quota(session, boss_account_id)
    if remaining < required:
        raise QuotaExceededError(
            f"配额不足：剩余 {remaining}，需要 {required}"
        )
    return remaining


async def record_consumption(
    session: AsyncSession,
    boss_account_id: str,
    candidate_id: int | None,
    result: str,
    *,
    quota_consumed: int = 1,
    detail: dict | None = None,
) -> OperationLog:
    """记录一次打招呼消耗.

    Args:
        session: 数据库 async session.
        boss_account_id: Boss 账号 ID.
        candidate_id: 候选人 ID（可选）.
        result: 操作结果（success/failed/quota_exceeded）.
        quota_consumed: 消耗配额数（失败时可为 0）.
        detail: 操作详情 JSON.

    Returns:
        创建的 OperationLog 记录.
    """
    log = OperationLog(
        op_type=_OP_TYPE_GREETING,
        boss_account_id=boss_account_id,
        candidate_id=candidate_id,
        result=result,
        quota_consumed=quota_consumed,
        detail=detail,
    )
    session.add(log)
    await session.flush()
    logger.info(
        "quota_consumed",
        boss_account_id=boss_account_id,
        candidate_id=candidate_id,
        result=result,
        quota_consumed=quota_consumed,
    )
    return log
