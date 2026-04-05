"""C1 流程编排 — 推荐列表抓取 → 详情提取 → 去重入库."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.c1_scraper.browser import BrowserManager
from src.c1_scraper.candidate_store import store_candidates
from src.c1_scraper.detail_extractor import CandidateDetail, parse_candidate_detail
from src.c1_scraper.recommend_scraper import RecommendScraper
from src.common.logger import get_logger
from src.common.models import Candidate

logger = get_logger(__name__)


async def run_c1_pipeline(
    browser_manager: BrowserManager,
    session: AsyncSession,
    *,
    boss_account_id: str = "",
    job_id: str = "",
    max_candidates: int = 50,
) -> list[Candidate]:
    """执行 C1 完整流程：抓取 → 解析 → 入库.

    Args:
        browser_manager: 已初始化的浏览器管理器（async with 块内）
        session: 数据库 async session
        boss_account_id: 来源 Boss 账号 ID
        job_id: 关联岗位 ID
        max_candidates: 最大抓取候选人数

    Returns:
        本次新增入库的 Candidate 列表（供 C2 打分）
    """
    # 1. 抓取推荐列表
    scraper = RecommendScraper(browser_manager, scroll_interval_ms=1500)
    recommend_list = await scraper.scrape(max_candidates=max_candidates)
    logger.info("pipeline_scrape_done", recommend_count=len(recommend_list))

    if not recommend_list:
        logger.info("pipeline_no_candidates")
        return []

    # 2. 从 raw_json 提取详情
    details: list[CandidateDetail] = []
    for rc in recommend_list:
        detail = parse_candidate_detail(rc.raw_json)
        if detail is not None:
            details.append(detail)
        else:
            logger.warning(
                "pipeline_detail_parse_failed",
                encrypt_geek_id=rc.encrypt_geek_id,
            )

    logger.info(
        "pipeline_detail_extracted",
        detail_count=len(details),
        failed_count=len(recommend_list) - len(details),
    )

    # 3. 去重入库
    new_candidates = await store_candidates(
        session,
        details,
        boss_account_id=boss_account_id,
        job_id=job_id,
    )
    logger.info(
        "pipeline_complete",
        new_count=len(new_candidates),
        total_scraped=len(recommend_list),
    )

    return new_candidates
