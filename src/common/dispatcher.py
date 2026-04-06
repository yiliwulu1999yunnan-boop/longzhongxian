"""消息分发器 — 根据企业微信消息内容路由到对应的处理逻辑."""

from __future__ import annotations

import re
from typing import Any

from src.c4_contact.command_parser import is_greeting_command
from src.common.logger import get_logger

logger = get_logger(__name__)

# 回调类型
ScreeningCallback = Any  # Callable[[str], Awaitable[None]]  — receives from_user
GreetingCallback = Any  # Callable[[str, str], Awaitable[None]]  — receives from_user, content
AnalyzeCallback = Any  # Callable[[str, str], Awaitable[None]]  — receives from_user, param
_screening_callback: ScreeningCallback | None = None
_greeting_callback: GreetingCallback | None = None
_analyze_callback: AnalyzeCallback | None = None

# 指令模式
_PATTERN_SCREENING = re.compile(r"^筛选(候选人)?$")
_PATTERN_ANALYZE = re.compile(r"^分析候选人\s*(.+)$")


class CommandType:
    """指令类型常量."""

    SCREENING = "screening_command"
    GREETING = "greeting_command"
    ANALYZE = "analyze_command"
    UNKNOWN = "unknown_command"
    SKIP_NON_TEXT = "skip_non_text"
    SKIP_EMPTY = "skip_empty"


def classify_command(content: str) -> tuple[str, str]:
    """分类指令，返回 (command_type, 提取的参数).

    Args:
        content: 消息文本内容（已 strip）.

    Returns:
        (command_type, param) — param 对于 analyze 是候选人名，其余为空字符串.
    """
    if not content:
        return CommandType.SKIP_EMPTY, ""

    # 筛选候选人
    if _PATTERN_SCREENING.match(content):
        return CommandType.SCREENING, ""

    # 分析候选人XXX
    m = _PATTERN_ANALYZE.match(content)
    if m:
        return CommandType.ANALYZE, m.group(1).strip()

    # 打招呼指令
    if is_greeting_command(content):
        return CommandType.GREETING, ""

    return CommandType.UNKNOWN, ""


async def dispatch_message(message: dict[str, str]) -> str:
    """根据消息内容分发到对应处理器.

    Args:
        message: 解密后的企业微信消息字段
            (from_user, to_user, msg_type, content, create_time).

    Returns:
        处理结果描述（用于日志和路由识别）.
    """
    msg_type = message.get("msg_type", "")
    content = message.get("content", "").strip()
    from_user = message.get("from_user", "")

    if msg_type != "text":
        logger.info("dispatch_skip_non_text", msg_type=msg_type, from_user=from_user)
        return CommandType.SKIP_NON_TEXT

    cmd_type, param = classify_command(content)

    logger.info(
        f"dispatch_{cmd_type}",
        from_user=from_user,
        content=content,
        param=param,
    )

    # 路由到对应回调
    if cmd_type == CommandType.SCREENING and _screening_callback is not None:
        await _screening_callback(from_user)
    elif cmd_type == CommandType.GREETING and _greeting_callback is not None:
        await _greeting_callback(from_user, content)
    elif cmd_type == CommandType.ANALYZE and param and _analyze_callback is not None:
        await _analyze_callback(from_user, param)

    return cmd_type


def register_screening_callback(callback: ScreeningCallback | None) -> None:
    """注册筛选指令的回调函数."""
    global _screening_callback  # noqa: PLW0603
    _screening_callback = callback


def register_greeting_callback(callback: GreetingCallback | None) -> None:
    """注册打招呼指令的回调函数."""
    global _greeting_callback  # noqa: PLW0603
    _greeting_callback = callback


def register_analyze_callback(callback: AnalyzeCallback | None) -> None:
    """注册分析候选人指令的回调函数."""
    global _analyze_callback  # noqa: PLW0603
    _analyze_callback = callback
