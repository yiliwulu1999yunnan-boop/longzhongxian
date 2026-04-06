"""页面安全检测 — 验证码 / 账号封禁 / 异常登录检测."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from playwright.async_api import Page

from src.common.logger import get_logger

logger = get_logger(__name__)


class PageThreat(str, Enum):
    """页面威胁类型."""

    CAPTCHA = "captcha"
    BAN = "ban"
    LOGIN_REDIRECT = "login_redirect"
    NONE = "none"


@dataclass(frozen=True)
class PageCheckResult:
    """页面安全检测结果."""

    threat: PageThreat
    detail: str = ""


# Boss 直聘已知的登录/安全拦截 URL 路径
_LOGIN_URL_PATTERNS = [
    "/web/user/login",
    "/web/user/safe",
    "/web/common/security",
]

# 验证码相关选择器
_CAPTCHA_SELECTORS = [
    "div.verify-wrap",
    "div.captcha-container",
    'div.dialog-wrap:has-text("验证")',
    'div.dialog-wrap:has-text("安全验证")',
    'iframe[src*="captcha"]',
    'div[class*="verify"]',
]

# 账号限制/封禁相关选择器
_BAN_SELECTORS = [
    'div:has-text("账号被限制")',
    'div:has-text("操作频繁")',
    'div:has-text("账号异常")',
    'div:has-text("访问受限")',
]


async def check_page_safety(page: Page) -> PageCheckResult:
    """检查页面是否出现验证码、封禁或登录跳转.

    在每次 page.goto() 之后调用，快速判断页面状态。

    Args:
        page: 当前 Playwright 页面.

    Returns:
        PageCheckResult 包含威胁类型和详情。
    """
    # 1. URL 检测：是否被跳转到登录页
    current_url = page.url
    for pattern in _LOGIN_URL_PATTERNS:
        if pattern in current_url:
            logger.warning("page_login_redirect_detected", url=current_url)
            return PageCheckResult(
                threat=PageThreat.LOGIN_REDIRECT,
                detail=f"页面跳转到登录页: {current_url}",
            )

    # 2. 验证码检测
    for selector in _CAPTCHA_SELECTORS:
        try:
            if await page.locator(selector).count() > 0:
                logger.warning("page_captcha_detected", selector=selector)
                return PageCheckResult(
                    threat=PageThreat.CAPTCHA,
                    detail=f"检测到验证码: {selector}",
                )
        except Exception:
            pass

    # 3. 账号限制检测
    for selector in _BAN_SELECTORS:
        try:
            if await page.locator(selector).count() > 0:
                logger.warning("page_ban_detected", selector=selector)
                return PageCheckResult(
                    threat=PageThreat.BAN,
                    detail=f"检测到账号限制: {selector}",
                )
        except Exception:
            pass

    return PageCheckResult(threat=PageThreat.NONE)
