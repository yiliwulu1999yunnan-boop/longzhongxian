"""C4 流程编排 — 检查配额 → 逐个打招呼 → 汇总结果 → 推送通知."""

from __future__ import annotations

from dataclasses import dataclass, field

from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from src.c3_push.channel import PushChannel
from src.c4_contact.greeting_sender import GreetingOutcome, GreetingResult, send_greeting
from src.c4_contact.quota_manager import (
    QuotaExceededError,
    check_quota,
    get_remaining_quota,
    record_consumption,
)
from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class GreetingTarget:
    """打招呼目标候选人."""

    candidate_id: int
    encrypt_geek_id: str
    detail_url: str
    greeting_message: str
    name: str = ""


@dataclass
class PipelineResult:
    """C4 pipeline 执行结果."""

    success_count: int = 0
    failed_count: int = 0
    quota_exhausted: bool = False
    remaining_quota: int = 0
    outcomes: list[GreetingOutcome] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """生成结果摘要文本."""
        parts = [
            f"打招呼完成：成功 {self.success_count} 个",
            f"失败 {self.failed_count} 个",
            f"配额剩余 {self.remaining_quota}",
        ]
        if self.quota_exhausted:
            parts.append("（配额已耗尽）")
        return "，".join(parts)


async def run_c4_pipeline(
    page: Page,
    session: AsyncSession,
    channel: PushChannel,
    *,
    targets: list[GreetingTarget],
    boss_account_id: str,
    wechat_userid: str,
) -> PipelineResult:
    """执行 C4 打招呼流程.

    Args:
        page: Playwright 页面实例.
        session: 数据库 async session.
        channel: 企业微信推送通道.
        targets: 打招呼目标候选人列表.
        boss_account_id: Boss 账号 ID（用于配额管理）.
        wechat_userid: 店长企业微信 userid（用于结果通知）.

    Returns:
        PipelineResult 包含执行结果.
    """
    result = PipelineResult()

    if not targets:
        logger.info("c4_pipeline_no_targets")
        result.remaining_quota = await get_remaining_quota(session, boss_account_id)
        await _send_notification(channel, wechat_userid, result)
        return result

    # 检查配额
    try:
        await check_quota(session, boss_account_id, required=len(targets))
    except QuotaExceededError:
        remaining = await get_remaining_quota(session, boss_account_id)
        if remaining == 0:
            result.quota_exhausted = True
            result.remaining_quota = 0
            await _send_notification(channel, wechat_userid, result)
            return result
        # 配额不够全部，但还有剩余，执行部分
        targets = targets[:remaining]
        logger.info(
            "c4_pipeline_partial_quota",
            requested=len(targets),
            remaining=remaining,
        )

    # 逐个执行打招呼
    for target in targets:
        outcome = await send_greeting(
            page,
            detail_url=target.detail_url,
            encrypt_geek_id=target.encrypt_geek_id,
            greeting_message=target.greeting_message,
        )
        result.outcomes.append(outcome)

        if outcome.result == GreetingResult.SUCCESS:
            result.success_count += 1
            await record_consumption(
                session, boss_account_id, target.candidate_id, "success"
            )
        elif outcome.result == GreetingResult.QUOTA_EXHAUSTED:
            result.quota_exhausted = True
            await record_consumption(
                session, boss_account_id, target.candidate_id,
                "quota_exceeded", quota_consumed=0,
            )
            logger.warning("c4_pipeline_quota_exhausted_mid_batch")
            break
        else:
            result.failed_count += 1
            await record_consumption(
                session, boss_account_id, target.candidate_id,
                "failed", quota_consumed=0,
                detail={"result": outcome.result.value, "detail": outcome.detail},
            )

    result.remaining_quota = await get_remaining_quota(session, boss_account_id)
    await session.commit()

    # 推送结果通知
    await _send_notification(channel, wechat_userid, result)

    logger.info(
        "c4_pipeline_completed",
        success=result.success_count,
        failed=result.failed_count,
        quota_exhausted=result.quota_exhausted,
        remaining=result.remaining_quota,
    )
    return result


async def _send_notification(
    channel: PushChannel,
    wechat_userid: str,
    result: PipelineResult,
) -> None:
    """推送执行结果通知给店长."""
    try:
        await channel.send_text(wechat_userid, result.summary)
    except Exception as exc:
        logger.error("c4_notification_failed", error=str(exc))
