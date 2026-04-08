"""推荐列表 /wapi/ 拦截 + 候选人数据解析."""

import random
from typing import Any

from playwright.async_api import Page, Response

from src.c1_scraper.browser import BrowserManager
from src.c1_scraper.models import RecommendCandidate
from src.common.logger import get_logger

logger = get_logger(__name__)

# 匹配推荐列表数据接口
_RECOMMEND_API_PATTERNS = [
    "/wapi/zpblock/recommend/major/data",
    "/wapi/batch/requests",
]

_DEFAULT_SCROLL_MIN_MS = 1500
_DEFAULT_SCROLL_MAX_MS = 3000


def parse_recommend_response(data: dict[str, Any]) -> list[RecommendCandidate]:
    """解析推荐列表接口 JSON，提取候选人列表.

    支持两种格式：
    - 直接格式: zpData.geekList
    - batch 格式: zpData 内嵌套多个子请求结果
    """
    candidates: list[RecommendCandidate] = []

    zp_data = data.get("zpData")
    if not isinstance(zp_data, dict):
        return candidates

    # 直接格式
    geek_list = zp_data.get("geekList")
    if isinstance(geek_list, list):
        for item in geek_list:
            candidate = _parse_geek_item(item)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    # batch 格式：遍历子请求结果
    for value in zp_data.values():
        if isinstance(value, dict):
            nested_list = value.get("geekList")
            if isinstance(nested_list, list):
                for item in nested_list:
                    candidate = _parse_geek_item(item)
                    if candidate is not None:
                        candidates.append(candidate)

    return candidates


def _parse_geek_item(item: Any) -> RecommendCandidate | None:
    """解析单个候选人 JSON 对象."""
    if not isinstance(item, dict):
        logger.warning("invalid_geek_item", item_type=type(item).__name__)
        return None

    encrypt_geek_id = item.get("encryptGeekId")
    geek_name = item.get("geekName")

    if not encrypt_geek_id or not geek_name:
        logger.warning(
            "missing_required_fields",
            has_id=bool(encrypt_geek_id),
            has_name=bool(geek_name),
        )
        return None

    card = item.get("geekCard") or {}
    detail_url = item.get("detailUrl", "")

    return RecommendCandidate(
        encrypt_geek_id=encrypt_geek_id,
        geek_name=geek_name,
        detail_url=detail_url,
        job_name=card.get("jobName", ""),
        city_name=card.get("cityName", ""),
        work_years=card.get("workYears", ""),
        age=card.get("age", ""),
        education=card.get("education", ""),
        gender=card.get("gender", ""),
        raw_json=item,
    )


class RecommendScraper:
    """推荐列表抓取器 — 拦截 /wapi/ 接口获取候选人数据."""

    def __init__(
        self,
        browser_manager: BrowserManager,
        *,
        scroll_min_ms: int = _DEFAULT_SCROLL_MIN_MS,
        scroll_max_ms: int = _DEFAULT_SCROLL_MAX_MS,
    ) -> None:
        self._mgr = browser_manager
        self._scroll_min_ms = scroll_min_ms
        self._scroll_max_ms = scroll_max_ms

    async def scrape(self, max_candidates: int = 50) -> list[RecommendCandidate]:
        """抓取推荐列表候选人.

        Args:
            max_candidates: 最大候选人数量

        Returns:
            解析后的候选人列表
        """
        collected: list[RecommendCandidate] = []

        async def _on_response(response: Response) -> None:
            url = response.url
            if not any(p in url for p in _RECOMMEND_API_PATTERNS):
                return
            try:
                body = await response.json()
                parsed = parse_recommend_response(body)
                collected.extend(parsed)
                # 记录原始响应顶层 key 便于诊断解析失败
                top_keys = list(body.keys()) if isinstance(body, dict) else []
                zp_data = body.get("zpData") if isinstance(body, dict) else None
                zp_keys = list(zp_data.keys()) if isinstance(zp_data, dict) else []
                logger.info(
                    "recommend_response_intercepted",
                    url=url[:100],
                    candidates_found=len(parsed),
                    top_keys=top_keys[:10],
                    zp_data_keys=zp_keys[:10],
                )
            except Exception:
                logger.warning("recommend_response_parse_error", url=url[:100])

        # 在 context 级别注册监听，覆盖 iframe 内的请求
        self._mgr.context.on("response", _on_response)

        page = await self._mgr.navigate_to_recommend()
        await page.wait_for_timeout(5000)

        # 滚动加载更多
        while len(collected) < max_candidates:
            prev_count = len(collected)
            await self._scroll_page(page)
            delay_ms = random.randint(self._scroll_min_ms, self._scroll_max_ms)
            await page.wait_for_timeout(delay_ms)

            if len(collected) == prev_count:
                # 没有新数据加载，停止滚动
                logger.info("scroll_no_new_data", total=len(collected))
                break

        result = collected[:max_candidates]
        logger.info("scrape_complete", total=len(result))
        return result

    @staticmethod
    async def _scroll_page(page: Page) -> None:
        """滚动页面触发加载更多（用键盘模拟，避免 evaluate 暴露自动化）."""
        await page.keyboard.press("End")
