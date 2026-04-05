"""候选人持久化 — encryptGeekId 去重 + 入库."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.c1_scraper.detail_extractor import CandidateDetail
from src.common.logger import get_logger
from src.common.models import Candidate

logger = get_logger(__name__)


async def store_candidates(
    session: AsyncSession,
    details: list[CandidateDetail],
    *,
    boss_account_id: str = "",
    job_id: str = "",
) -> list[Candidate]:
    """去重后入库，返回本次新增的候选人列表.

    Args:
        session: 数据库 async session
        details: 解析后的候选人详情列表
        boss_account_id: 来源 Boss 账号 ID
        job_id: 关联岗位 ID

    Returns:
        本次新增入库的 Candidate ORM 对象列表（供 C2 打分使用）
    """
    if not details:
        return []

    # 批量查询已存在的 encrypt_geek_id
    geek_ids = [d.encrypt_geek_id for d in details]
    result = await session.execute(
        select(Candidate.encrypt_geek_id).where(
            Candidate.encrypt_geek_id.in_(geek_ids)
        )
    )
    existing_ids: set[str] = {row[0] for row in result}

    new_candidates: list[Candidate] = []
    for detail in details:
        if detail.encrypt_geek_id in existing_ids:
            logger.debug(
                "candidate_already_exists",
                encrypt_geek_id=detail.encrypt_geek_id,
            )
            continue

        candidate = Candidate(
            encrypt_geek_id=detail.encrypt_geek_id,
            raw_json=detail.raw_json,
            detail_url=detail.detail_url,
            boss_account_id=boss_account_id or None,
            job_id=job_id or None,
        )
        session.add(candidate)
        new_candidates.append(candidate)
        existing_ids.add(detail.encrypt_geek_id)  # 防止同批次内重复

    if new_candidates:
        await session.flush()
        logger.info(
            "candidates_stored",
            new_count=len(new_candidates),
            skipped_count=len(details) - len(new_candidates),
        )

    return new_candidates
