"""消息分发器 — 根据企业微信消息内容路由到对应的处理逻辑."""

from __future__ import annotations

from src.c4_contact.command_parser import is_greeting_command
from src.common.logger import get_logger

logger = get_logger(__name__)


async def dispatch_message(message: dict[str, str]) -> str:
    """根据消息内容分发到对应处理器.

    Args:
        message: 解密后的企���微信消息字段
            (from_user, to_user, msg_type, content, create_time).

    Returns:
        处理结果描述（用于日志）.
    """
    msg_type = message.get("msg_type", "")
    content = message.get("content", "").strip()
    from_user = message.get("from_user", "")

    if msg_type != "text":
        logger.info("dispatch_skip_non_text", msg_type=msg_type, from_user=from_user)
        return "skip_non_text"

    if not content:
        logger.info("dispatch_skip_empty", from_user=from_user)
        return "skip_empty"

    # 打招呼指令路由
    if is_greeting_command(content):
        logger.info(
            "dispatch_greeting_command",
            from_user=from_user,
            content=content,
        )
        # 实际执行逻辑在 C4.3 pipeline 中编排，这里只做路由识别
        return "greeting_command"

    logger.info(
        "dispatch_unknown_command",
        from_user=from_user,
        content=content,
    )
    return "unknown_command"
