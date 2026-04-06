"""Playwright 打招呼执行器 — 在 Boss 直聘对指定候选人发送打招呼消息."""

import asyncio
import random
from dataclasses import dataclass
from enum import Enum

from playwright.async_api import Page

from src.common.logger import get_logger

logger = get_logger(__name__)

# ───────── DOM 选择器（Boss 直聘推荐牛人详情页） ─────────

# "立即沟通"按钮
_BTN_GREETING = 'a.btn-startchat, button.btn-startchat, div.op-btn-chat'
# 消息输入框（聊天页）
_INPUT_MESSAGE = 'div.chat-input div[contenteditable="true"], textarea.chat-input'
# 发送按钮
_BTN_SEND = 'button.btn-send, div.chat-op button:has-text("发送")'
# 配额耗尽 / 付费弹窗
_DIALOG_PAYWALL = 'div.dialog-container:has-text("直聊卡"), div.dialog-wrap:has-text("沟通次数")'
# 推荐列表中候选人卡片
_CARD_ITEM = 'div.recommend-card-wrap, li.card-item'


class GreetingResult(str, Enum):
    """打招呼结果."""

    SUCCESS = "success"
    QUOTA_EXHAUSTED = "quota_exhausted"
    ALREADY_GREETED = "already_greeted"
    CANDIDATE_NOT_FOUND = "candidate_not_found"
    PAGE_ERROR = "page_error"


@dataclass(frozen=True)
class GreetingOutcome:
    """单次打招呼操作的结果."""

    encrypt_geek_id: str
    result: GreetingResult
    detail: str = ""


async def _random_delay(min_sec: float = 0.5, max_sec: float = 2.0) -> None:
    """随机延迟，降低反自动化检测风险."""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def _check_paywall(page: Page) -> bool:
    """检测付费弹窗（配额耗尽）."""
    paywall = page.locator(_DIALOG_PAYWALL)
    return await paywall.count() > 0


async def _try_send_on_chat_page(page: Page, message: str) -> GreetingResult:
    """在已跳转到聊天页后输入消息并发送.

    Returns:
        GreetingResult
    """
    # 等待输入框出现
    input_box = page.locator(_INPUT_MESSAGE).first
    try:
        await input_box.wait_for(state="visible", timeout=5000)
    except Exception:
        # 可能已经打过招呼，直接在聊天界面
        logger.info("greeting_input_not_found_may_already_greeted")
        return GreetingResult.ALREADY_GREETED

    await _random_delay(0.3, 0.8)
    await input_box.fill(message)
    await _random_delay(0.3, 0.6)

    send_btn = page.locator(_BTN_SEND).first
    await send_btn.click()
    await _random_delay(0.5, 1.0)

    # 检查是否弹出付费弹窗
    if await _check_paywall(page):
        logger.warning("greeting_quota_exhausted_after_send")
        return GreetingResult.QUOTA_EXHAUSTED

    logger.info("greeting_send_success")
    return GreetingResult.SUCCESS


async def send_greeting(
    page: Page,
    *,
    detail_url: str,
    encrypt_geek_id: str,
    greeting_message: str,
) -> GreetingOutcome:
    """主路径：导航到候选人详情页 → 点击打招呼 → 输入消息 → 发送.

    Args:
        page: Playwright 页面实例
        detail_url: 候选人详情页 URL
        encrypt_geek_id: 候选人加密 ID（用于日志和结果追踪）
        greeting_message: 打招呼消息文本（≤150 字）

    Returns:
        GreetingOutcome 包含操作结果
    """
    try:
        await page.goto(detail_url, wait_until="domcontentloaded", timeout=15000)
        await _random_delay(1.0, 2.0)

        # 检查付费弹窗
        if await _check_paywall(page):
            return GreetingOutcome(
                encrypt_geek_id=encrypt_geek_id,
                result=GreetingResult.QUOTA_EXHAUSTED,
                detail="付费弹窗出现，配额可能已耗尽",
            )

        # 点击"立即沟通 / 打招呼"按钮
        greeting_btn = page.locator(_BTN_GREETING).first
        try:
            await greeting_btn.wait_for(state="visible", timeout=5000)
        except Exception:
            logger.warning(
                "greeting_btn_not_found",
                encrypt_geek_id=encrypt_geek_id,
                url=detail_url,
            )
            return GreetingOutcome(
                encrypt_geek_id=encrypt_geek_id,
                result=GreetingResult.ALREADY_GREETED,
                detail="未找到打招呼按钮，可能已沟通过",
            )

        await _random_delay(0.3, 0.8)
        await greeting_btn.click()
        await _random_delay(1.0, 2.0)

        # 点击后可能跳转到聊天页面或弹出输入框
        result = await _try_send_on_chat_page(page, greeting_message)
        return GreetingOutcome(
            encrypt_geek_id=encrypt_geek_id,
            result=result,
        )

    except Exception as exc:
        logger.error(
            "greeting_error",
            encrypt_geek_id=encrypt_geek_id,
            error=str(exc),
        )
        return GreetingOutcome(
            encrypt_geek_id=encrypt_geek_id,
            result=GreetingResult.PAGE_ERROR,
            detail=str(exc),
        )


async def send_greeting_fallback(
    page: Page,
    *,
    encrypt_geek_id: str,
    candidate_name: str,
    greeting_message: str,
) -> GreetingOutcome:
    """降级路径：详情页 URL 失效时，在推荐列表页滚动查找候选人.

    Args:
        page: 已经在推荐列表页的 Playwright 页面
        encrypt_geek_id: 候选人加密 ID
        candidate_name: 候选人姓名（用于列表页定位）
        greeting_message: 打招呼消息文本

    Returns:
        GreetingOutcome
    """
    try:
        # 在列表页查找候选人卡片
        max_scroll = 10
        for _ in range(max_scroll):
            # 按名字查找
            card = page.locator(f'{_CARD_ITEM}:has-text("{candidate_name}")').first
            if await card.count() > 0:
                await _random_delay(0.3, 0.8)
                await card.click()
                await _random_delay(1.0, 2.0)

                # 点击后进入详情或聊天，尝试发送
                result = await _try_send_on_chat_page(page, greeting_message)
                return GreetingOutcome(
                    encrypt_geek_id=encrypt_geek_id,
                    result=result,
                )

            # 未找到，向下滚动
            await page.mouse.wheel(0, 500)
            await _random_delay(0.5, 1.0)

        return GreetingOutcome(
            encrypt_geek_id=encrypt_geek_id,
            result=GreetingResult.CANDIDATE_NOT_FOUND,
            detail=f"滚动 {max_scroll} 次未找到候选人: {candidate_name}",
        )

    except Exception as exc:
        logger.error(
            "greeting_fallback_error",
            encrypt_geek_id=encrypt_geek_id,
            error=str(exc),
        )
        return GreetingOutcome(
            encrypt_geek_id=encrypt_geek_id,
            result=GreetingResult.PAGE_ERROR,
            detail=str(exc),
        )
