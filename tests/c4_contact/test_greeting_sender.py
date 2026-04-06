"""Tests for c4_contact/greeting_sender — 全部 mock，不实际访问 Boss 直聘."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.c4_contact.greeting_sender import (
    GreetingResult,
    _DIALOG_PAYWALL,
    send_greeting,
    send_greeting_fallback,
)
from src.common.page_guard import PageCheckResult, PageThreat


@pytest.fixture(autouse=True)
def _mock_page_guard():
    """统一 mock page_guard，避免验证码选择器与 paywall 选择器冲突."""
    with patch(
        "src.common.page_guard.check_page_safety",
        new=AsyncMock(return_value=PageCheckResult(threat=PageThreat.NONE)),
    ):
        yield


# ───────── Helpers ─────────


def _make_locator(*, count: int = 0, visible: bool = True) -> AsyncMock:
    """创建 mock Playwright Locator."""
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=count)
    if visible:
        loc.wait_for = AsyncMock()
    else:
        loc.wait_for = AsyncMock(side_effect=TimeoutError("not visible"))
    loc.click = AsyncMock()
    loc.fill = AsyncMock()
    loc.first = loc  # .first 返回自身
    return loc


def _make_page(
    *,
    paywall_visible: bool = False,
    greeting_btn_visible: bool = True,
    input_visible: bool = True,
) -> AsyncMock:
    """创建 mock Playwright Page，配置各选择器的行为."""
    page = AsyncMock()
    page.goto = AsyncMock()

    def locator_factory(selector: str) -> AsyncMock:
        if "dialog" in selector or "paywall" in selector or selector == _DIALOG_PAYWALL:
            return _make_locator(count=1 if paywall_visible else 0)
        if "startchat" in selector or "op-btn-chat" in selector:
            return _make_locator(visible=greeting_btn_visible)
        if "contenteditable" in selector or "chat-input" in selector:
            return _make_locator(visible=input_visible)
        if "btn-send" in selector or "发送" in selector:
            return _make_locator()
        if "card-item" in selector or "recommend-card" in selector:
            return _make_locator(count=1)
        return _make_locator()

    page.locator = MagicMock(side_effect=locator_factory)

    # mouse.wheel for scroll
    page.mouse = AsyncMock()
    page.mouse.wheel = AsyncMock()

    return page


# ───────── send_greeting 主路径测��� ─────────


@pytest.mark.asyncio()
async def test_send_greeting_success() -> None:
    """正常流程：导航 → 点击打招呼 → 输入消息 → 发送成功."""
    page = _make_page()

    outcome = await send_greeting(
        page,
        detail_url="https://www.zhipin.com/web/geek/detail/123",
        encrypt_geek_id="geek_abc",
        greeting_message="���好，我们是笼中仙",
    )

    assert outcome.result == GreetingResult.SUCCESS
    assert outcome.encrypt_geek_id == "geek_abc"
    page.goto.assert_awaited_once()


@pytest.mark.asyncio()
async def test_send_greeting_quota_exhausted_on_detail() -> None:
    """详情页加载后检测到付费弹窗 → 配额耗尽."""
    page = _make_page(paywall_visible=True)

    outcome = await send_greeting(
        page,
        detail_url="https://www.zhipin.com/web/geek/detail/123",
        encrypt_geek_id="geek_abc",
        greeting_message="您好",
    )

    assert outcome.result == GreetingResult.QUOTA_EXHAUSTED


@pytest.mark.asyncio()
async def test_send_greeting_already_greeted() -> None:
    """打招呼按钮不存在 → 已沟通过."""
    page = _make_page(greeting_btn_visible=False)

    outcome = await send_greeting(
        page,
        detail_url="https://www.zhipin.com/web/geek/detail/123",
        encrypt_geek_id="geek_abc",
        greeting_message="您好",
    )

    assert outcome.result == GreetingResult.ALREADY_GREETED


@pytest.mark.asyncio()
async def test_send_greeting_page_error() -> None:
    """页面导航异常 → PAGE_ERROR."""
    page = AsyncMock()
    page.goto = AsyncMock(side_effect=Exception("net::ERR_CONNECTION_REFUSED"))
    page.locator = MagicMock(return_value=_make_locator(count=0))

    outcome = await send_greeting(
        page,
        detail_url="https://invalid.example.com",
        encrypt_geek_id="geek_err",
        greeting_message="您好",
    )

    assert outcome.result == GreetingResult.PAGE_ERROR
    assert "ERR_CONNECTION_REFUSED" in outcome.detail


@pytest.mark.asyncio()
async def test_send_greeting_input_not_found_already_greeted() -> None:
    """点击打招呼后，输入框不出现 → 判定为已沟通过."""
    page = _make_page(input_visible=False)

    outcome = await send_greeting(
        page,
        detail_url="https://www.zhipin.com/web/geek/detail/123",
        encrypt_geek_id="geek_abc",
        greeting_message="您好",
    )

    assert outcome.result == GreetingResult.ALREADY_GREETED


# ──��────── send_greeting_fallback 降级路径测试 ─────────


@pytest.mark.asyncio()
async def test_fallback_finds_candidate() -> None:
    """降级路径：在列表页找到候选人并发送成功."""
    page = _make_page()

    outcome = await send_greeting_fallback(
        page,
        encrypt_geek_id="geek_fb",
        candidate_name="张三",
        greeting_message="您好，我们是笼中仙",
    )

    assert outcome.result == GreetingResult.SUCCESS
    assert outcome.encrypt_geek_id == "geek_fb"


@pytest.mark.asyncio()
async def test_fallback_candidate_not_found() -> None:
    """降级路径：滚动多次仍未找到候选人."""
    page = AsyncMock()
    page.mouse = AsyncMock()
    page.mouse.wheel = AsyncMock()

    # 所有卡片选择器返回 count=0
    def locator_factory(selector: str) -> AsyncMock:
        return _make_locator(count=0)

    page.locator = MagicMock(side_effect=locator_factory)

    outcome = await send_greeting_fallback(
        page,
        encrypt_geek_id="geek_nf",
        candidate_name="不存在的人",
        greeting_message="您好",
    )

    assert outcome.result == GreetingResult.CANDIDATE_NOT_FOUND
    assert "不存在的人" in outcome.detail


@pytest.mark.asyncio()
async def test_fallback_page_error() -> None:
    """降级路径：页面操作异常."""
    page = AsyncMock()
    page.mouse = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.locator = MagicMock(side_effect=Exception("DOM destroyed"))

    outcome = await send_greeting_fallback(
        page,
        encrypt_geek_id="geek_err",
        candidate_name="李四",
        greeting_message="您好",
    )

    assert outcome.result == GreetingResult.PAGE_ERROR
    assert "DOM destroyed" in outcome.detail
