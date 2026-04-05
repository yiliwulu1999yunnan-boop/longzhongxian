"""聊天记录抓取 — 优先 /wapi/ JSON 接口，DOM 解析兜底."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from playwright.async_api import Page, Response

from src.common.logger import get_logger

logger = get_logger(__name__)

# Boss 直聘沟通页
BOSS_CHAT_URL = "https://www.zhipin.com/web/chat/index"

# 聊天消息 API
_CHAT_API_PATTERN = "/wapi/zpitem/web/chat/message/list/box"

# 消息类型映射
_MSG_TYPE_TEXT = 1
_MSG_TYPE_IMAGE = 3
_MSG_TYPE_EMOJI = 5
_MSG_TYPE_FILE = 6
_MSG_TYPE_VIDEO = 7

# DOM 选择器
_CHAT_LIST_ITEM = 'li.chat-item, div.chat-record'
_CHAT_SEARCH_INPUT = 'input.search-input, input[placeholder*="搜索"]'
_CHAT_CONTACT_ITEM = 'li.user-item, div.chat-user-item'
_CHAT_MESSAGE_ITEM = 'div.msg-item, div.chat-msg-item'
_CHAT_MSG_TEXT = 'span.text, div.msg-text, div.text'
_CHAT_MSG_TIME = 'span.time, div.msg-time'
_CHAT_MSG_SENDER = 'span.name, div.msg-name'


@dataclass(frozen=True)
class ChatMessage:
    """单条聊天消息."""

    message_id: str
    sender_name: str
    sender_uid: str
    content: str
    timestamp: datetime
    is_from_boss: bool
    msg_type: str = "text"


def parse_chat_api_response(data: dict[str, Any]) -> list[ChatMessage]:
    """解析 /wapi/ 聊天接口返回的 JSON.

    Args:
        data: 接口 JSON 响应.

    Returns:
        按时间排序的聊天消息列表.
    """
    messages: list[ChatMessage] = []

    zp_data = data.get("zpData")
    if not isinstance(zp_data, dict):
        return messages

    msg_list = zp_data.get("messages")
    if not isinstance(msg_list, list):
        return messages

    for item in msg_list:
        msg = _parse_message_item(item)
        if msg is not None:
            messages.append(msg)

    # 按时间排序
    messages.sort(key=lambda m: m.timestamp)
    return messages


def _parse_message_item(item: dict[str, Any]) -> ChatMessage | None:
    """解析单条消息."""
    if not isinstance(item, dict):
        return None

    mid = item.get("mid", "")
    msg_type_code = item.get("type", 0)
    body = item.get("body", {})
    from_info = item.get("from", {})
    time_ms = item.get("time", 0)

    # 解析内容
    content, msg_type = _extract_content(msg_type_code, body)

    # 解析时间
    if time_ms:
        timestamp = datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc)
    else:
        timestamp = datetime.now(timezone.utc)

    # 判断是否为 Boss 发送（uid 中包含 boss 或 from 的 name 含"店长"等）
    sender_uid = from_info.get("uid", "")
    sender_name = from_info.get("name", "")
    is_from_boss = "boss" in sender_uid.lower() or sender_uid.startswith("boss")

    return ChatMessage(
        message_id=str(mid),
        sender_name=sender_name,
        sender_uid=sender_uid,
        content=content,
        timestamp=timestamp,
        is_from_boss=is_from_boss,
        msg_type=msg_type,
    )


def _extract_content(msg_type_code: int, body: dict[str, Any]) -> tuple[str, str]:
    """根据消息类型提取内容文本.

    Returns:
        (content, msg_type_str)
    """
    if msg_type_code == _MSG_TYPE_TEXT:
        return body.get("text", ""), "text"
    elif msg_type_code == _MSG_TYPE_IMAGE:
        return "[图片]", "image"
    elif msg_type_code == _MSG_TYPE_EMOJI:
        return "[表情]", "emoji"
    elif msg_type_code == _MSG_TYPE_FILE:
        return "[文件]", "file"
    elif msg_type_code == _MSG_TYPE_VIDEO:
        return "[视频]", "video"
    else:
        return f"[未知消息类型:{msg_type_code}]", "unknown"


async def scrape_chat_via_api(
    page: Page,
    encrypt_geek_id: str,
) -> list[ChatMessage] | None:
    """通过拦截 /wapi/ 接口获取聊天记录.

    Args:
        page: Playwright 页面实例.
        encrypt_geek_id: 候选人加密 ID.

    Returns:
        聊天消息列表，接口未返回数据时返回 None（触发 DOM 兜底）.
    """
    captured_data: list[dict[str, Any]] = []

    async def on_response(response: Response) -> None:
        if _CHAT_API_PATTERN in response.url:
            try:
                data = await response.json()
                captured_data.append(data)
            except Exception:
                logger.debug("chat_api_response_parse_failed", url=response.url)

    page.on("response", on_response)

    try:
        # 导航到候选人聊天页面
        chat_url = f"{BOSS_CHAT_URL}?encryptGeekId={encrypt_geek_id}"
        await page.goto(chat_url, wait_until="domcontentloaded", timeout=15000)
        # 等待 API 响应
        await page.wait_for_timeout(3000)
    except Exception as exc:
        logger.warning("chat_api_navigation_failed", error=str(exc))
        return None
    finally:
        page.remove_listener("response", on_response)

    if not captured_data:
        logger.info("chat_api_no_data", encrypt_geek_id=encrypt_geek_id)
        return None

    # 合并所有捕获的消息
    all_messages: list[ChatMessage] = []
    for data in captured_data:
        all_messages.extend(parse_chat_api_response(data))

    logger.info(
        "chat_api_scraped",
        encrypt_geek_id=encrypt_geek_id,
        message_count=len(all_messages),
    )
    return all_messages


async def scrape_chat_via_dom(page: Page) -> list[ChatMessage]:
    """DOM 兜底：从聊天界面直接解析消息元素.

    Args:
        page: 已经在聊天页面的 Playwright 页面.

    Returns:
        解析出的聊天消息列表.
    """
    messages: list[ChatMessage] = []

    msg_elements = page.locator(_CHAT_MESSAGE_ITEM)
    count = await msg_elements.count()

    for i in range(count):
        el = msg_elements.nth(i)
        try:
            text_el = el.locator(_CHAT_MSG_TEXT).first
            text = await text_el.text_content() or ""
            text = text.strip()

            sender_el = el.locator(_CHAT_MSG_SENDER).first
            sender = ""
            if await sender_el.count() > 0:
                sender = (await sender_el.text_content() or "").strip()

            time_el = el.locator(_CHAT_MSG_TIME).first
            if await time_el.count() > 0:
                await time_el.text_content()  # 预留后续时间解析

            # 非文本消息识别
            content, msg_type = _classify_dom_content(text)

            messages.append(
                ChatMessage(
                    message_id=f"dom_{i}",
                    sender_name=sender,
                    sender_uid="",
                    content=content,
                    timestamp=datetime.now(timezone.utc),
                    is_from_boss=False,
                    msg_type=msg_type,
                )
            )
        except Exception:
            logger.debug("dom_message_parse_failed", index=i)
            continue

    logger.info("chat_dom_scraped", message_count=len(messages))
    return messages


def _classify_dom_content(text: str) -> tuple[str, str]:
    """识别 DOM 提取的文本是否为非文本消息.

    Returns:
        (content, msg_type)
    """
    if not text:
        return "[空消息]", "empty"
    if text in ("[图片]", "[图片消息]"):
        return "[图片]", "image"
    if text in ("[表情]", "[表情消息]"):
        return "[表情]", "emoji"
    if text in ("[文件]", "[文件消息]"):
        return "[文件]", "file"
    if text in ("[视频]", "[视频消息]"):
        return "[视频]", "video"
    return text, "text"


async def scrape_chat(
    page: Page,
    encrypt_geek_id: str,
) -> list[ChatMessage]:
    """获取候选人聊天记录：优先 API，失败则 DOM 兜底.

    Args:
        page: Playwright 页面实例.
        encrypt_geek_id: 候选人加密 ID.

    Returns:
        聊天消息列表.
    """
    # 优先尝试 API
    api_messages = await scrape_chat_via_api(page, encrypt_geek_id)
    if api_messages is not None and len(api_messages) > 0:
        return api_messages

    # DOM 兜底
    logger.info("chat_fallback_to_dom", encrypt_geek_id=encrypt_geek_id)
    return await scrape_chat_via_dom(page)
