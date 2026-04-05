"""筛选报告推送服务 — 查找店长 userid 并通过企业微信发送报告."""

from __future__ import annotations

import logging

from src.c3_push.channel import PushChannel
from src.c3_push.report_builder import ReportResult
from src.common.account_mapping import (
    StoreAccountInfo,
    get_account_by_boss_id,
)

logger = logging.getLogger(__name__)

# 最大重试次数
_MAX_RETRIES = 2


class ReportSendError(Exception):
    """报告推送失败."""


async def send_report(
    channel: PushChannel,
    report: ReportResult,
    boss_account_id: str,
    *,
    yaml_path: str = "config/store_accounts.yaml",
    max_retries: int = _MAX_RETRIES,
) -> StoreAccountInfo:
    """将筛选报告推送给对应店长.

    Args:
        channel: 推送通道（企业微信实现）.
        report: C3.1 生成的报告结果.
        boss_account_id: Boss 直聘账号 ID，用于查找店长 userid.
        yaml_path: 账号映射 YAML 配置路径.
        max_retries: 发送失败最大重试次数.

    Returns:
        成功推送时返回店长账号信息.

    Raises:
        AccountNotFoundError: 找不到 boss_account_id 对应的店长.
        ReportSendError: 重试耗尽仍发送失败.
    """
    account = get_account_by_boss_id(boss_account_id, yaml_path)
    user_id = account.wechat_userid

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 2):  # max_retries + 1 次尝试
        try:
            await channel.send_markdown(user_id, report.markdown)
            logger.info(
                "报告推送成功: userid=%s, boss=%s, attempt=%d",
                user_id, boss_account_id, attempt,
            )
            return account
        except Exception as exc:
            last_error = exc
            logger.warning(
                "报告推送失败 (attempt %d/%d): userid=%s, error=%s",
                attempt, max_retries + 1, user_id, exc,
            )

    raise ReportSendError(
        f"报告推送失败，已重试 {max_retries} 次: {last_error}"
    ) from last_error
