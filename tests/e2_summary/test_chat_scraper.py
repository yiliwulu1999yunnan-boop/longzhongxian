"""Tests for e2_summary/chat_scraper — 聊天记录抓取（全 mock）."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.e2_summary.chat_scraper import (
    parse_chat_api_response,
    scrape_chat,
    scrape_chat_via_dom,
)

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _load_fixture() -> dict:
    return json.loads(
        (_FIXTURES_DIR / "wapi_chat_response.json").read_text("utf-8")
    )


# ───────── parse_chat_api_response：/wapi/ JSON 解析 ─────────


def test_parse_full_response() -> None:
    """正确解析完整的 /wapi/ 聊天接口响应."""
    data = _load_fixture()
    messages = parse_chat_api_response(data)

    assert len(messages) == 5
    # 应按时间排序
    for i in range(len(messages) - 1):
        assert messages[i].timestamp <= messages[i + 1].timestamp


def test_parse_text_messages() -> None:
    """文本消息正确提取内容和发送方."""
    data = _load_fixture()
    messages = parse_chat_api_response(data)

    # 第一条：Boss 发送
    msg0 = messages[0]
    assert msg0.msg_type == "text"
    assert "笼中仙" in msg0.content
    assert msg0.sender_name == "张店长"
    assert msg0.is_from_boss

    # 第二条：候选人回复
    msg1 = messages[1]
    assert msg1.msg_type == "text"
    assert "工作时间" in msg1.content
    assert msg1.sender_name == "李*"
    assert not msg1.is_from_boss


def test_parse_image_message() -> None:
    """图片消息标记为 [图片] 占位符."""
    data = _load_fixture()
    messages = parse_chat_api_response(data)

    image_msgs = [m for m in messages if m.msg_type == "image"]
    assert len(image_msgs) == 1
    assert image_msgs[0].content == "[图片]"


def test_parse_emoji_message() -> None:
    """表情消息标记为 [表情] 占位符."""
    data = _load_fixture()
    messages = parse_chat_api_response(data)

    emoji_msgs = [m for m in messages if m.msg_type == "emoji"]
    assert len(emoji_msgs) == 1
    assert emoji_msgs[0].content == "[表情]"


def test_parse_timestamp() -> None:
    """时间戳正确转换为 datetime."""
    data = _load_fixture()
    messages = parse_chat_api_response(data)

    msg0 = messages[0]
    # 1712300000000 ms → 2024-04-05 某时刻
    assert msg0.timestamp.tzinfo is not None
    assert msg0.timestamp.year == 2024


def test_parse_empty_zpdata() -> None:
    """zpData 为空时返回空列表."""
    assert parse_chat_api_response({"code": 0}) == []
    assert parse_chat_api_response({"code": 0, "zpData": "invalid"}) == []


def test_parse_no_messages() -> None:
    """zpData 中无 messages 字段时返回空列表."""
    assert parse_chat_api_response({"code": 0, "zpData": {}}) == []


def test_parse_unknown_msg_type() -> None:
    """未知消息类型不崩溃，标记为 [未知消息类型:X]."""
    data = {
        "code": 0,
        "zpData": {
            "messages": [
                {
                    "mid": "m1",
                    "type": 99,
                    "body": {},
                    "from": {"uid": "u1", "name": "A"},
                    "to": {"uid": "u2", "name": "B"},
                    "time": 1712300000000,
                }
            ]
        },
    }
    messages = parse_chat_api_response(data)
    assert len(messages) == 1
    assert messages[0].msg_type == "unknown"
    assert "99" in messages[0].content


def test_parse_message_id_is_string() -> None:
    """message_id 始终为字符串."""
    data = _load_fixture()
    messages = parse_chat_api_response(data)
    for msg in messages:
        assert isinstance(msg.message_id, str)


# ───────── scrape_chat_via_dom：DOM 兜底解析 ─────────


def _make_dom_page(texts: list[str]) -> AsyncMock:
    """创建 mock page，模拟 DOM 消息元素."""
    page = AsyncMock()

    msg_locator = AsyncMock()
    msg_locator.count = AsyncMock(return_value=len(texts))

    def nth(i: int) -> AsyncMock:
        el = AsyncMock()

        text_loc = AsyncMock()
        text_loc.text_content = AsyncMock(return_value=texts[i])
        text_loc.count = AsyncMock(return_value=1)

        sender_loc = AsyncMock()
        sender_loc.count = AsyncMock(return_value=0)
        sender_loc.text_content = AsyncMock(return_value="")

        time_loc = AsyncMock()
        time_loc.count = AsyncMock(return_value=0)
        time_loc.text_content = AsyncMock(return_value="")

        def locator_factory(selector: str) -> AsyncMock:
            if "text" in selector.lower():
                loc = AsyncMock()
                loc.first = text_loc
                return loc
            if "name" in selector.lower():
                loc = AsyncMock()
                loc.first = sender_loc
                return loc
            if "time" in selector.lower():
                loc = AsyncMock()
                loc.first = time_loc
                return loc
            loc = AsyncMock()
            loc.first = AsyncMock()
            loc.first.count = AsyncMock(return_value=0)
            return loc

        el.locator = MagicMock(side_effect=locator_factory)
        return el

    msg_locator.nth = MagicMock(side_effect=nth)

    page.locator = MagicMock(return_value=msg_locator)
    return page


@pytest.mark.asyncio()
async def test_dom_extracts_text_messages() -> None:
    """DOM 解析能提取对话文本内容."""
    page = _make_dom_page(["你好", "可以聊聊", "好的"])
    messages = await scrape_chat_via_dom(page)

    assert len(messages) == 3
    assert messages[0].content == "你好"
    assert messages[0].msg_type == "text"


@pytest.mark.asyncio()
async def test_dom_image_placeholder() -> None:
    """DOM 解析中图片消息标记为占位符."""
    page = _make_dom_page(["[图片]"])
    messages = await scrape_chat_via_dom(page)

    assert len(messages) == 1
    assert messages[0].content == "[图片]"
    assert messages[0].msg_type == "image"


@pytest.mark.asyncio()
async def test_dom_emoji_placeholder() -> None:
    """DOM 解析中表情消息标记为占位符."""
    page = _make_dom_page(["[表情]"])
    messages = await scrape_chat_via_dom(page)

    assert len(messages) == 1
    assert messages[0].content == "[表情]"
    assert messages[0].msg_type == "emoji"


@pytest.mark.asyncio()
async def test_dom_empty_message() -> None:
    """DOM 解析空消息不崩溃."""
    page = _make_dom_page(["", "正常消息"])
    messages = await scrape_chat_via_dom(page)

    assert len(messages) == 2
    assert messages[0].content == "[空消息]"
    assert messages[1].content == "正常消息"


@pytest.mark.asyncio()
async def test_dom_no_messages() -> None:
    """DOM 无消息元素时返回空列表."""
    page = _make_dom_page([])
    messages = await scrape_chat_via_dom(page)
    assert messages == []


@pytest.mark.asyncio()
async def test_dom_parse_exception_skips() -> None:
    """DOM 解析单条异常时跳过，不影响其他."""
    page = AsyncMock()
    msg_locator = AsyncMock()
    msg_locator.count = AsyncMock(return_value=2)

    def nth(i: int) -> AsyncMock:
        el = AsyncMock()
        if i == 0:
            # 第一条抛异常
            el.locator = MagicMock(side_effect=Exception("DOM error"))
        else:
            text_loc = AsyncMock()
            text_loc.text_content = AsyncMock(return_value="正常")
            text_loc.count = AsyncMock(return_value=1)
            sender_loc = AsyncMock()
            sender_loc.count = AsyncMock(return_value=0)
            time_loc = AsyncMock()
            time_loc.count = AsyncMock(return_value=0)

            def locator_factory(selector: str) -> AsyncMock:
                if "text" in selector.lower():
                    loc = AsyncMock()
                    loc.first = text_loc
                    return loc
                if "name" in selector.lower():
                    loc = AsyncMock()
                    loc.first = sender_loc
                    return loc
                if "time" in selector.lower():
                    loc = AsyncMock()
                    loc.first = time_loc
                    return loc
                loc = AsyncMock()
                loc.first = AsyncMock()
                loc.first.count = AsyncMock(return_value=0)
                return loc

            el.locator = MagicMock(side_effect=locator_factory)
        return el

    msg_locator.nth = MagicMock(side_effect=nth)
    page.locator = MagicMock(return_value=msg_locator)

    messages = await scrape_chat_via_dom(page)
    assert len(messages) == 1
    assert messages[0].content == "正常"


# ───────── scrape_chat：API 优先 + DOM 兜底 ─────────


@pytest.mark.asyncio()
async def test_scrape_chat_prefers_api() -> None:
    """API 返回数据时使用 API 结果，不走 DOM."""
    page = AsyncMock()
    fixture_data = _load_fixture()

    # mock API 拦截：page.on("response", cb) 注册回调
    captured_callbacks: list = []

    def fake_on(event: str, cb: object) -> None:
        if event == "response":
            captured_callbacks.append(cb)

    page.on = MagicMock(side_effect=fake_on)
    page.remove_listener = MagicMock()

    async def fake_goto(*args, **kwargs):  # noqa: ANN002, ANN003
        # 模拟 API 响应触发回调
        mock_response = AsyncMock()
        mock_response.url = "https://www.zhipin.com/wapi/zpitem/web/chat/message/list/box?id=1"
        mock_response.json = AsyncMock(return_value=fixture_data)
        for cb in captured_callbacks:
            await cb(mock_response)

    page.goto = AsyncMock(side_effect=fake_goto)
    page.wait_for_timeout = AsyncMock()

    messages = await scrape_chat(page, "geek_abc")
    assert len(messages) == 5


@pytest.mark.asyncio()
async def test_scrape_chat_falls_back_to_dom() -> None:
    """API 无数据时降级到 DOM 解析."""
    page = _make_dom_page(["你好", "再见"])

    # mock API 拦截：无数据
    page.on = MagicMock()
    page.remove_listener = MagicMock()
    page.goto = AsyncMock()
    page.wait_for_timeout = AsyncMock()

    messages = await scrape_chat(page, "geek_abc")
    assert len(messages) == 2
    assert messages[0].content == "你好"
