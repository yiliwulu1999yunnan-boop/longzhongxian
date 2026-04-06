"""Playwright 浏览器上下文管理 — 支持 CDP 连接（生产）和 launch 模式（测试）."""

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

from src.common.circuit_breaker import CircuitBreaker
from src.common.config import get_settings
from src.common.logger import get_logger
from src.common.retry import retry_with_backoff
from src.common.storage_state import check_storage_state

logger = get_logger(__name__)

BOSS_RECOMMEND_URL = "https://www.zhipin.com/web/chat/recommend"

# 反检测基础配置（仅 launch 模式使用）
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_DEFAULT_VIEWPORT = ViewportSize(width=1920, height=1080)
_DEFAULT_LOCALE = "zh-CN"

_VALID_SAME_SITE = {"Strict", "Lax", "None"}


class PageBlockedError(Exception):
    """页面被安全机制拦截（验证码/封禁/登录跳转）."""

    def __init__(self, threat: str, detail: str = "") -> None:
        self.threat = threat
        self.detail = detail
        super().__init__(f"页面拦截 [{threat}]: {detail}")


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

    支持两种模式：
    - CDP 模式（生产）：connect_over_cdp() 连接用户已打开的浏览器，
      使用 browser.contexts[0] 继承真实登录态。
    - Launch 模式（测试/兼容）：launch() 新开浏览器 + storageState 隔离。
    """

    def __init__(
        self,
        storage_state_path: str = "",
        *,
        headless: bool = True,
        cdp_endpoint: str = "",
    ) -> None:
        # 确定 CDP endpoint：参数优先，其次读配置
        self._cdp_endpoint = cdp_endpoint or get_settings().cdp_endpoint

        self._storage_state_path = storage_state_path
        self._headless = headless
        self._expiry_warning = False

        # Legacy 模式：检查 storageState
        if not self._cdp_endpoint:
            if not storage_state_path:
                raise ValueError(
                    "必须提供 storage_state_path 或 cdp_endpoint（通过参数或环境变量 CDP_ENDPOINT）"
                )
            status = check_storage_state(storage_state_path)
            if status.expired:
                logger.warning(
                    "storage_state_expired",
                    path=storage_state_path,
                    days=status.days_since_modified,
                )
            elif status.days_since_modified is not None and status.days_since_modified > 5.0:
                logger.warning(
                    "storage_state_expiry_soon",
                    path=storage_state_path,
                    days=status.days_since_modified,
                    expires_in_days=round(7.0 - status.days_since_modified, 1),
                )
                self._expiry_warning = True

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._circuit = CircuitBreaker(
            "browser", failure_threshold=3, recovery_seconds=120.0
        )

    @property
    def storage_state_expiry_warning(self) -> bool:
        """StorageState 是否即将过期（剩余 ≤2 天）."""
        return self._expiry_warning

    async def __aenter__(self) -> "BrowserManager":
        self._playwright = await async_playwright().start()

        if self._cdp_endpoint:
            # CDP 模式：连接用户已打开的浏览器
            try:
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    self._cdp_endpoint,
                    timeout=10000,
                )
            except Exception as exc:
                await self._playwright.stop()
                self._playwright = None
                raise RuntimeError(
                    f"无法连接到 Chrome CDP ({self._cdp_endpoint})。"
                    "请确保浏览器已启动并开启了 --remote-debugging-port。"
                    f"原始错误: {exc}"
                ) from exc

            # 使用浏览器的默认上下文（保留真实登录态）
            if self._browser.contexts:
                self._context = self._browser.contexts[0]
            else:
                self._context = await self._browser.new_context()
                logger.warning("cdp_no_existing_context_created_new")

            self._page = await self._context.new_page()
            logger.info("browser_cdp_connected", endpoint=self._cdp_endpoint)
        else:
            # Launch 模式：新开浏览器 + storageState
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless,
            )
            state = _normalize_storage_state(self._storage_state_path)
            self._context = await self._browser.new_context(
                storage_state=state,
                user_agent=_DEFAULT_USER_AGENT,
                viewport=_DEFAULT_VIEWPORT,
                locale=_DEFAULT_LOCALE,
            )
            self._page = await self._context.new_page()
            logger.info(
                "browser_context_created",
                storage_state=self._storage_state_path,
            )

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        # 关闭我们创建的 tab
        if self._page:
            await self._page.close()

        if self._cdp_endpoint:
            # CDP 模式：只断开连接，不关闭浏览器/上下文
            if self._browser:
                await self._browser.close()  # CDP 下仅断开连接
        else:
            # Launch 模式：关闭所有资源
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()

        if self._playwright:
            await self._playwright.stop()

        logger.info("browser_session_ended")

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

    @property
    def circuit(self) -> CircuitBreaker:
        """浏览器操作熔断器."""
        return self._circuit

    async def navigate_to_recommend(self) -> Page:
        """导航到 Boss 直聘推荐列表页（含熔断 + 重试）."""
        self._circuit.check()

        async def _do_navigate() -> Page:
            page = self.page
            await page.goto(BOSS_RECOMMEND_URL, wait_until="domcontentloaded")

            # 页面安全检测（延迟导入避免循环依赖）
            from src.common import page_guard

            result = await page_guard.check_page_safety(page)
            if result.threat != page_guard.PageThreat.NONE:
                raise PageBlockedError(result.threat.value, result.detail)

            return page

        try:
            page = await retry_with_backoff(
                _do_navigate,
                max_retries=2,
                base_delay=2.0,
                max_delay=15.0,
                retryable=lambda exc: not isinstance(exc, PageBlockedError),
            )
        except PageBlockedError:
            self._circuit.record_failure()
            raise
        except Exception:
            self._circuit.record_failure()
            raise
        else:
            self._circuit.record_success()

        logger.info("navigated_to_recommend", url=BOSS_RECOMMEND_URL)
        return page
