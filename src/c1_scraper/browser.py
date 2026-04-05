"""Playwright 浏览器上下文管理 — 多账号 storageState 隔离."""

import json
from pathlib import Path
from types import TracebackType
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    StorageState,
    ViewportSize,
    async_playwright,
)

from src.common.logger import get_logger
from src.common.storage_state import check_storage_state

logger = get_logger(__name__)

BOSS_RECOMMEND_URL = "https://www.zhipin.com/web/boss/recommend"

# 反检测基础配置
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_DEFAULT_VIEWPORT = ViewportSize(width=1920, height=1080)
_DEFAULT_LOCALE = "zh-CN"

_VALID_SAME_SITE = {"Strict", "Lax", "None"}


def _normalize_storage_state(path: str) -> "StorageState":
    """读取 storageState JSON 并修正 Cookie 字段格式.

    浏览器 cookieStore API 导出的 sameSite 为小写（"lax"），
    Playwright 要求首字母大写（"Lax"）。
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for cookie in data.get("cookies", []):
        raw = cookie.get("sameSite", "Lax")
        capitalized = raw.capitalize() if isinstance(raw, str) else "Lax"
        cookie["sameSite"] = capitalized if capitalized in _VALID_SAME_SITE else "Lax"
    return data


class BrowserManager:
    """Playwright 浏览器上下文管理器.

    按 storageState 文件创建隔离的 browser context，
    支持 async with 语法自动管理生命周期。
    """

    def __init__(self, storage_state_path: str, *, headless: bool = True) -> None:
        status = check_storage_state(storage_state_path)
        if status.expired:
            logger.warning(
                "storage_state_expired",
                path=storage_state_path,
                days=status.days_since_modified,
            )
        self._storage_state_path = storage_state_path
        self._headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> "BrowserManager":
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        state = _normalize_storage_state(self._storage_state_path)
        self._context = await self._browser.new_context(
            storage_state=state,
            user_agent=_DEFAULT_USER_AGENT,
            viewport=_DEFAULT_VIEWPORT,
            locale=_DEFAULT_LOCALE,
        )
        self._page = await self._context.new_page()
        logger.info("browser_context_created", storage_state=self._storage_state_path)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("browser_context_closed", storage_state=self._storage_state_path)

    @property
    def page(self) -> Page:
        """当前页面，仅在 async with 块内可用."""
        if self._page is None:
            raise RuntimeError("BrowserManager 未启动，请在 async with 块内使用")
        return self._page

    @property
    def context(self) -> BrowserContext:
        """当前浏览器上下文，仅在 async with 块内可用."""
        if self._context is None:
            raise RuntimeError("BrowserManager 未启动，请在 async with 块内使用")
        return self._context

    async def navigate_to_recommend(self) -> Page:
        """导航到 Boss 直聘推荐列表页."""
        page = self.page
        await page.goto(BOSS_RECOMMEND_URL, wait_until="domcontentloaded")
        logger.info("navigated_to_recommend", url=BOSS_RECOMMEND_URL)
        return page
