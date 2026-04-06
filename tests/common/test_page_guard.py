"""page_guard 单元测试 — 验证码/封禁/登录跳转检测."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from src.common.page_guard import PageThreat, check_page_safety


def _make_locator(count: int = 0) -> MagicMock:
    """构造 mock Locator（locator 本身是同步的，count() 是异步的）."""
    loc = MagicMock()
    loc.count = AsyncMock(return_value=count)
    return loc


def _make_page(
    url: str = "https://www.zhipin.com/web/chat/recommend",
    *,
    captcha_count: int = 0,
    ban_count: int = 0,
) -> MagicMock:
    """构造 mock Page，可配置 URL 和特定选择器的元素数量."""
    page = MagicMock()
    type(page).url = PropertyMock(return_value=url)

    def locator_factory(selector: str) -> MagicMock:
        if "verify" in selector or "captcha" in selector or "验证" in selector:
            return _make_locator(captcha_count)
        if "限制" in selector or "频繁" in selector or "异常" in selector or "受限" in selector:
            return _make_locator(ban_count)
        return _make_locator(0)

    page.locator = MagicMock(side_effect=locator_factory)
    return page


@pytest.mark.asyncio()
async def test_safe_page_returns_none_threat() -> None:
    """正常页面应返回 NONE 威胁."""
    page = _make_page()
    result = await check_page_safety(page)
    assert result.threat == PageThreat.NONE
    assert result.detail == ""


@pytest.mark.asyncio()
async def test_login_redirect_detected() -> None:
    """URL 包含登录路径时检测为 LOGIN_REDIRECT."""
    page = _make_page(url="https://www.zhipin.com/web/user/login?redirect=/web/chat")
    result = await check_page_safety(page)
    assert result.threat == PageThreat.LOGIN_REDIRECT
    assert "登录页" in result.detail


@pytest.mark.asyncio()
async def test_security_url_detected() -> None:
    """URL 包含 security 路径时检测为 LOGIN_REDIRECT."""
    page = _make_page(url="https://www.zhipin.com/web/common/security/check")
    result = await check_page_safety(page)
    assert result.threat == PageThreat.LOGIN_REDIRECT


@pytest.mark.asyncio()
async def test_captcha_detected() -> None:
    """页面存在验证码元素时检测为 CAPTCHA."""
    page = _make_page(captcha_count=1)
    result = await check_page_safety(page)
    assert result.threat == PageThreat.CAPTCHA
    assert "验证码" in result.detail


@pytest.mark.asyncio()
async def test_ban_detected() -> None:
    """页面存在账号限制元素时检测为 BAN."""
    page = _make_page(ban_count=1)
    result = await check_page_safety(page)
    assert result.threat == PageThreat.BAN
    assert "账号限制" in result.detail


@pytest.mark.asyncio()
async def test_locator_exception_is_swallowed() -> None:
    """locator 抛异常时不影响后续检测."""
    page = MagicMock()
    type(page).url = PropertyMock(return_value="https://www.zhipin.com/web/chat/recommend")

    call_count = 0

    def locator_side_effect(selector: str) -> MagicMock:
        nonlocal call_count
        call_count += 1
        loc = MagicMock()
        if call_count == 1:
            # 第一个选择器抛异常
            loc.count = AsyncMock(side_effect=Exception("element detached"))
        else:
            loc.count = AsyncMock(return_value=0)
        return loc

    page.locator = MagicMock(side_effect=locator_side_effect)
    result = await check_page_safety(page)
    assert result.threat == PageThreat.NONE


@pytest.mark.asyncio()
async def test_priority_login_over_captcha() -> None:
    """URL 登录跳转优先于 DOM 验证码检测."""
    page = _make_page(
        url="https://www.zhipin.com/web/user/login",
        captcha_count=1,
    )
    result = await check_page_safety(page)
    assert result.threat == PageThreat.LOGIN_REDIRECT
