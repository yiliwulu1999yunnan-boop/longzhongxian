"""筛选链路编排 — 串联 C1 → C2 → C3 完成候选人筛选全流程."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from src.c1_scraper.browser import BrowserManager
from src.c1_scraper.detail_extractor import CandidateDetail, parse_candidate_detail
from src.c1_scraper.pipeline import run_c1_pipeline
from src.c2_scorer.hard_rules import CandidateInfo
from src.c2_scorer.llm_scorer import LlmScorer
from src.c2_scorer.pipeline import run_c2_pipeline
from src.c2_scorer.profile_loader import JobProfile
from src.c3_push.channel import PushChannel
from src.c3_push.report_builder import ScoredCandidate, build_report
from src.c3_push.report_sender import send_report
from src.common.logger import get_logger
from src.common.models import Candidate, OperationLog

logger = get_logger(__name__)


@dataclass
class ScreeningResult:
    """筛选链路完整输出."""

    candidates_scraped: int
    candidates_scored: int
    report_sent: bool
    error: str | None = None
    number_mapping: dict[int, int] = field(default_factory=dict)


def _candidate_to_info(detail: CandidateDetail) -> CandidateInfo:
    """将 C1 的 CandidateDetail 转换为 C2 的 CandidateInfo."""
    age: int | None = None
    if detail.age:
        # age 格式如 "25岁"
        digits = "".join(c for c in detail.age if c.isdigit())
        if digits:
            age = int(digits)

    work_years: float | None = None
    if detail.work_years:
        digits = "".join(c for c in detail.work_years if c.isdigit())
        if digits:
            work_years = float(digits)

    return CandidateInfo(
        age=age,
        education=detail.degree or None,
        work_experience_years=work_years,
    )


def _candidate_to_text(detail: CandidateDetail) -> str:
    """将 C1 的 CandidateDetail 拼接为 LLM 评估用文本."""
    parts: list[str] = []
    parts.append(f"姓名: {detail.geek_name}")
    if detail.age:
        parts.append(f"年龄: {detail.age}")
    if detail.work_years:
        parts.append(f"工作年限: {detail.work_years}")
    if detail.degree:
        parts.append(f"学历: {detail.degree}")
    if detail.expect_position:
        parts.append(f"期望职位: {detail.expect_position}")
    if detail.salary:
        parts.append(f"期望薪资: {detail.salary}")
    if detail.self_desc:
        parts.append(f"自我描述: {detail.self_desc}")
    for exp in detail.work_experiences:
        line = f"工作经历: {exp.company} - {exp.position_name}"
        if exp.work_time:
            line += f" ({exp.work_time})"
        parts.append(line)
    for edu in detail.educations:
        line = f"教育经历: {edu.school} - {edu.major} ({edu.degree_name})"
        parts.append(line)
    return "\n".join(parts)


def _detail_from_candidate(candidate: Candidate) -> CandidateDetail | None:
    """从数据库 Candidate 的 raw_json 还原 CandidateDetail."""
    if not candidate.raw_json:
        return None
    return parse_candidate_detail(candidate.raw_json)


async def run_screening(
    browser_manager: BrowserManager,
    session: AsyncSession,
    channel: PushChannel,
    llm_scorer: LlmScorer,
    profile: JobProfile,
    *,
    boss_account_id: str,
    job_id: str = "",
    yaml_path: str = "config/store_accounts.yaml",
    dry_run: bool = False,
) -> ScreeningResult:
    """执行完整筛选链路：C1 抓取 → C2 打分 → C3 推送.

    Args:
        browser_manager: Playwright 浏览器管理器.
        session: 数据库 async session.
        channel: 企业微信推送通道.
        llm_scorer: LLM 评估器.
        profile: 岗位画像配置.
        boss_account_id: Boss 直聘账号 ID.
        job_id: 岗位 ID.
        yaml_path: 账号映射 YAML 路径.
        dry_run: True 时抓取和评分但不写库、不发推送，用于风控测试.

    Returns:
        ScreeningResult 包含流程执行结果（dry_run 时 report_sent 始终为 False）.
    """
    # ── StorageState 过期提前告警 ──
    if browser_manager.storage_state_expiry_warning:
        logger.warning("storage_state_expiry_soon_alert", boss=boss_account_id)
        await _notify_error(
            channel, boss_account_id,
            "Cookie 即将过期（≤2天），请尽快手动更新 storageState 文件",
            yaml_path,
        )

    # ── Step 1: C1 抓取 ──
    try:
        new_candidates = await run_c1_pipeline(
            browser_manager, session,
            boss_account_id=boss_account_id, job_id=job_id,
            dry_run=dry_run,
        )
    except Exception as exc:
        logger.error("screening_c1_failed", error=str(exc))
        if not dry_run:
            await _notify_error(channel, boss_account_id, f"简历获取失败: {exc}", yaml_path)
            await _log_operation(session, boss_account_id, "failed", f"C1 失败: {exc}")
        return ScreeningResult(
            candidates_scraped=0, candidates_scored=0,
            report_sent=False, error=f"C1 失败: {exc}",
        )

    if not new_candidates:
        logger.info("screening_no_new_candidates", boss=boss_account_id)
        if not dry_run:
            await _notify_error(channel, boss_account_id, "本次未发现新候选人", yaml_path)
            await _log_operation(session, boss_account_id, "success", "无新候选人")
        return ScreeningResult(
            candidates_scraped=0, candidates_scored=0, report_sent=True,
        )

    # ── Step 2: C2 打分 ──
    scored: list[ScoredCandidate] = []

    if dry_run:
        # Dry-run：C1 返回 CandidateDetail，直接在内存中打分
        details: list[CandidateDetail] = cast(list[CandidateDetail], new_candidates)
        for cdetail in details:
            try:
                c2_result = await run_c2_pipeline(
                    candidate_info=_candidate_to_info(cdetail),
                    candidate_text=_candidate_to_text(cdetail),
                    candidate_id=0,
                    profile=profile,
                    llm_scorer=llm_scorer,
                    session=session,
                    dry_run=True,
                )
            except Exception as exc:
                logger.error("screening_c2_failed", candidate_name=cdetail.geek_name, error=str(exc))
                continue

            scored.append(ScoredCandidate(
                candidate_id=0,
                name=cdetail.geek_name,
                merged=c2_result.merged,
                work_years=cdetail.work_years,
                age=cdetail.age,
            ))
    else:
        # 正常模式：C1 返回 Candidate ORM 对象
        candidates: list[Candidate] = cast(list[Candidate], new_candidates)
        for candidate in candidates:
            detail: CandidateDetail | None = _detail_from_candidate(candidate)
            if detail is None:
                logger.warning("screening_detail_unavailable", candidate_id=candidate.id)
                continue

            try:
                c2_result = await run_c2_pipeline(
                    candidate_info=_candidate_to_info(detail),
                    candidate_text=_candidate_to_text(detail),
                    candidate_id=candidate.id,
                    profile=profile,
                    llm_scorer=llm_scorer,
                    session=session,
                )
            except Exception as exc:
                logger.error(
                    "screening_c2_failed",
                    candidate_id=candidate.id, error=str(exc),
                )
                continue

            scored.append(ScoredCandidate(
                candidate_id=candidate.id,
                name=detail.geek_name,
                merged=c2_result.merged,
                work_years=detail.work_years,
                age=detail.age,
            ))

    # ── Step 3: C3 生成报告并推送 ──
    report = build_report(scored, job_name=profile.position_name)
    scraped_count = len(cast(list[CandidateDetail], new_candidates)) if dry_run else len(new_candidates)
    logger.info(
        "screening_dry_run_report",
        boss=boss_account_id,
        scraped=scraped_count,
        scored=len(scored),
        report_preview=report.markdown[:500],
    )

    report_sent = False
    if not dry_run:
        try:
            await send_report(
                channel, report, boss_account_id, yaml_path=yaml_path,
            )
            report_sent = True
        except Exception as exc:
            logger.error("screening_c3_failed", error=str(exc))

        await _log_operation(
            session, boss_account_id, "success" if report_sent else "failed",
            f"抓取{len(new_candidates)}人，评分{len(scored)}人，推送{'成功' if report_sent else '失败'}",
        )

    return ScreeningResult(
        candidates_scraped=len(new_candidates),
        candidates_scored=len(scored),
        report_sent=report_sent,
        number_mapping=report.number_mapping,
    )


async def _notify_error(
    channel: PushChannel,
    boss_account_id: str,
    message: str,
    yaml_path: str,
) -> None:
    """发送错误通知给店长."""
    try:
        from src.common.account_mapping import get_account_by_boss_id
        account = get_account_by_boss_id(boss_account_id, yaml_path)
        await channel.send_text(account.wechat_userid, f"⚠️ {message}")
    except Exception as exc:
        logger.error("screening_notify_error_failed", error=str(exc))


async def _log_operation(
    session: AsyncSession,
    boss_account_id: str,
    result: str,
    detail: str,
) -> None:
    """写入操作日志."""
    try:
        log = OperationLog(
            op_type="screening",
            boss_account_id=boss_account_id,
            result=result,
            detail={"message": detail},
        )
        session.add(log)
        await session.flush()
    except Exception as exc:
        logger.error("screening_log_failed", error=str(exc))
