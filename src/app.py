"""FastAPI 应用入口 — 健康检查 + 企业微信回调路由 + 异步任务调度."""

import os
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.c1_scraper.browser import BrowserManager
from src.c1_scraper.detail_extractor import parse_candidate_detail
from src.c2_scorer.llm_scorer import LlmScorer
from src.c2_scorer.profile_loader import load_profile
from src.c3_push.channel import WechatPushChannel
from src.c3_push.wechat_callback import (
    CallbackCryptoError,
    WechatCallbackCrypto,
    parse_text_message,
)
from src.c4_contact.command_parser import parse_greeting_command
from src.c4_contact.pipeline import GreetingTarget, run_c4_pipeline
from src.common.account_mapping import AccountNotFoundError, get_account_by_wechat_userid
from src.common.config import get_settings
from src.common.db import get_engine, get_session_factory
from src.common.dispatcher import (
    dispatch_message,
    register_analyze_callback,
    register_greeting_callback,
    register_screening_callback,
)
from src.common.logger import get_logger, setup_logging
from src.common.models import Candidate
from src.common.screening_pipeline import run_screening
from src.common.task_queue import TaskQueue
from src.e2_summary.chat_scraper import scrape_chat
from src.e2_summary.pipeline import run_e2_pipeline

logger = get_logger(__name__)

# 全局资源（在 lifespan 中初始化）
task_queue: TaskQueue | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

# 内存缓存：wechat_userid → 最近一次筛选报告的编号映射
_report_store: dict[str, dict[int, int]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动时初始化全局资源."""
    global task_queue, _session_factory  # noqa: PLW0603
    settings = get_settings()
    setup_logging(settings.log_level)

    # P0-2: 强制单 Worker — 多 worker 下并发抓取/打招呼会触发风控
    workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
    if workers > 1:
        logger.error("multi_worker_rejected", workers=workers)
        sys.exit("致命错误: 本系统必须以单 worker 运行，检测到 WEB_CONCURRENCY=%d" % workers)

    # 初始化数据库
    engine = get_engine(settings)
    _session_factory = get_session_factory(engine)

    task_queue = TaskQueue()

    # 注册指令回调 — 通过 task_queue 异步执行
    async def _on_screening(from_user: str) -> None:
        assert task_queue is not None
        await task_queue.submit(
            _run_screening_task, from_user, account_id=from_user,
        )

    async def _on_greeting(from_user: str, content: str) -> None:
        assert task_queue is not None
        await task_queue.submit(
            _run_greeting_task, from_user, content, account_id=from_user,
        )

    async def _on_analyze(from_user: str, candidate_name: str) -> None:
        assert task_queue is not None
        await task_queue.submit(
            _run_analyze_task, from_user, candidate_name, account_id=from_user,
        )

    register_screening_callback(_on_screening)
    register_greeting_callback(_on_greeting)
    register_analyze_callback(_on_analyze)

    logger.info("app_started")
    yield

    # 清理回调，防止测试间状态泄漏
    register_screening_callback(None)
    register_greeting_callback(None)
    register_analyze_callback(None)
    _session_factory = None
    _report_store.clear()
    await engine.dispose()
    logger.info("app_stopped")


app = FastAPI(title="笼中仙 AI 招聘助手", version="0.1.0", lifespan=lifespan)


# ───────── 任务函数 — 接入真实 pipeline ─────────


async def _notify_user(from_user: str, message: str) -> None:
    """向店长发送通知（最佳努力，不抛异常）."""
    try:
        channel = WechatPushChannel()
        await channel.send_text(from_user, message)
    except Exception as exc:
        logger.error("notify_user_failed", from_user=from_user, error=str(exc))


async def _run_screening_task(from_user: str) -> str:
    """筛选任务 — C1 抓取 → C2 打分 → C3 推送."""
    assert _session_factory is not None
    logger.info("screening_task_start", from_user=from_user)

    try:
        account = get_account_by_wechat_userid(from_user)
    except AccountNotFoundError:
        logger.error("screening_account_not_found", from_user=from_user)
        await _notify_user(from_user, "账号未配置，请联系管理员")
        return "error: account_not_found"

    try:
        profile = load_profile(account.job_type)
    except Exception as exc:
        logger.error("screening_profile_load_failed", job_type=account.job_type, error=str(exc))
        await _notify_user(from_user, f"岗位配置加载失败: {exc}")
        return f"error: profile_load_failed: {exc}"

    try:
        async with BrowserManager(account.storage_state_path) as bm:
            async with _session_factory() as session:
                channel = WechatPushChannel()
                llm_scorer = LlmScorer()
                result = await run_screening(
                    bm, session, channel, llm_scorer, profile,
                    boss_account_id=account.boss_account_id,
                    job_id=account.job_type,
                )
                await session.commit()
    except Exception as exc:
        logger.error("screening_task_failed", from_user=from_user, error=str(exc))
        await _notify_user(from_user, f"筛选任务执行失败: {exc}")
        return f"error: {exc}"

    # 缓存 number_mapping 供后续打招呼指令使用
    if result.number_mapping:
        _report_store[from_user] = result.number_mapping

    logger.info(
        "screening_task_done",
        from_user=from_user,
        scraped=result.candidates_scraped,
        scored=result.candidates_scored,
        report_sent=result.report_sent,
    )
    return "screening_done"


async def _run_greeting_task(from_user: str, content: str) -> str:
    """打招呼任务 — 解析指令 → 查候选人 → C4 打招呼."""
    assert _session_factory is not None
    logger.info("greeting_task_start", from_user=from_user, content=content)

    # 1. 获取上次筛选的编号映射
    number_mapping = _report_store.get(from_user)
    if not number_mapping:
        await _notify_user(from_user, "请先发送「筛选」获取候选人列表")
        return "error: no_report"

    # 2. 解析指令
    parsed = parse_greeting_command(content, number_mapping)
    if not parsed.ok:
        await _notify_user(from_user, f"指令解析失败: {parsed.error}")
        return f"error: parse_failed: {parsed.error}"

    try:
        account = get_account_by_wechat_userid(from_user)
    except AccountNotFoundError:
        logger.error("greeting_account_not_found", from_user=from_user)
        await _notify_user(from_user, "账号未配置，请联系管理员")
        return "error: account_not_found"

    # 3. 从 DB 查候选人并构建打招呼目标
    try:
        profile = load_profile(account.job_type)
    except Exception as exc:
        logger.error("greeting_profile_load_failed", error=str(exc))
        await _notify_user(from_user, f"岗位配置加载失败: {exc}")
        return f"error: profile_load_failed: {exc}"

    try:
        async with _session_factory() as session:
            stmt = select(Candidate).where(Candidate.id.in_(parsed.candidate_ids))
            rows = await session.execute(stmt)
            candidates = list(rows.scalars().all())

            targets: list[GreetingTarget] = []
            for c in candidates:
                detail = parse_candidate_detail(c.raw_json) if c.raw_json else None
                targets.append(GreetingTarget(
                    candidate_id=c.id,
                    encrypt_geek_id=c.encrypt_geek_id,
                    detail_url=c.detail_url or "",
                    greeting_message=profile.greeting_template,
                    name=detail.geek_name if detail else "",
                ))

            if not targets:
                await _notify_user(from_user, "未找到对应的候选人记录")
                return "error: no_candidates_found"

            # 4. 执行打招呼
            async with BrowserManager(account.storage_state_path) as bm:
                channel = WechatPushChannel()
                result = await run_c4_pipeline(
                    bm.page, session, channel,
                    targets=targets,
                    boss_account_id=account.boss_account_id,
                    wechat_userid=from_user,
                )
                await session.commit()
    except Exception as exc:
        logger.error("greeting_task_failed", from_user=from_user, error=str(exc))
        await _notify_user(from_user, f"打招呼任务执行失败: {exc}")
        return f"error: {exc}"

    logger.info(
        "greeting_task_done",
        from_user=from_user,
        success=result.success_count,
        failed=result.failed_count,
    )
    return "greeting_done"


async def _run_analyze_task(from_user: str, candidate_name: str) -> str:
    """分析任务 — 模糊匹配候选人 → 抓聊天记录 → E2 汇总."""
    assert _session_factory is not None
    logger.info("analyze_task_start", from_user=from_user, candidate=candidate_name)

    try:
        account = get_account_by_wechat_userid(from_user)
    except AccountNotFoundError:
        logger.error("analyze_account_not_found", from_user=from_user)
        await _notify_user(from_user, "账号未配置，请联系管理员")
        return "error: account_not_found"

    try:
        async with _session_factory() as session:
            # 1. 查该账号的候选人列表
            stmt = (
                select(Candidate)
                .where(Candidate.boss_account_id == account.boss_account_id)
                .order_by(Candidate.created_at.desc())
                .limit(100)
            )
            rows = await session.execute(stmt)
            db_candidates = list(rows.scalars().all())

            if not db_candidates:
                await _notify_user(from_user, "暂无候选人记录，请先执行筛选")
                return "error: no_candidates"

            # 构建候选人列表（用于模糊匹配）
            candidates_for_match: list[dict[str, str]] = []
            geek_id_map: dict[str, str] = {}
            for c in db_candidates:
                detail = parse_candidate_detail(c.raw_json) if c.raw_json else None
                name = detail.geek_name if detail else ""
                candidates_for_match.append({
                    "name": name,
                    "encrypt_geek_id": c.encrypt_geek_id,
                })
                geek_id_map[c.encrypt_geek_id] = name

            # 2. 通过浏览器抓取聊天记录
            # 先做模糊匹配，确定 encrypt_geek_id
            from src.e2_summary.summary_generator import fuzzy_match_candidate

            matched = fuzzy_match_candidate(candidate_name, candidates_for_match)
            if matched is None:
                await _notify_user(from_user, f"未找到匹配的候选人: {candidate_name}")
                return "error: candidate_not_matched"

            encrypt_geek_id = matched["encrypt_geek_id"]

            async with BrowserManager(account.storage_state_path) as bm:
                chat_messages = await scrape_chat(bm.page, encrypt_geek_id)

            # 3. 调用 E2 pipeline 生成汇总并推送
            channel = WechatPushChannel()
            e2_result = await run_e2_pipeline(
                candidate_query=candidate_name,
                candidates=candidates_for_match,
                chat_messages=chat_messages,
                push_channel=channel,
                push_user_id=from_user,
            )
    except Exception as exc:
        logger.error("analyze_task_failed", from_user=from_user, error=str(exc))
        await _notify_user(from_user, f"分析任务执行失败: {exc}")
        return f"error: {exc}"

    logger.info(
        "analyze_task_done",
        from_user=from_user,
        candidate=e2_result.candidate_name,
        pushed=e2_result.pushed,
    )
    return "analyze_done"


def _get_crypto() -> WechatCallbackCrypto:
    """创建企业微信回调加解密器."""
    settings = get_settings()
    return WechatCallbackCrypto(
        token=settings.wechat_token,
        encoding_aes_key=settings.wechat_encoding_aes_key,
        corp_id=settings.wechat_corp_id,
    )


# ───────── 健康检查 ─────────


@app.get("/health")
async def health_check() -> dict[str, str]:
    """健康检查端点."""
    return {"status": "ok"}


# ───────── 企业微信回调 ─────────


@app.get("/wechat/callback", response_class=PlainTextResponse)
async def wechat_callback_verify(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
) -> str:
    """企业微信回调 URL 验证（GET）— 解密并返回 echostr."""
    crypto = _get_crypto()
    try:
        plain = crypto.decrypt_callback_verify(msg_signature, timestamp, nonce, echostr)
    except CallbackCryptoError as exc:
        logger.warning("callback_verify_failed", error=str(exc))
        return "verify failed"
    return plain


@app.post("/wechat/callback", response_class=PlainTextResponse)
async def wechat_callback_receive(
    request: Request,
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
) -> str:
    """企业微信消息接收（POST）— 解密 XML 并交给 dispatcher."""
    body = await request.body()
    crypto = _get_crypto()
    try:
        decrypted_xml = crypto.decrypt_message(
            msg_signature, timestamp, nonce, body.decode("utf-8")
        )
    except CallbackCryptoError as exc:
        logger.warning("callback_decrypt_failed", error=str(exc))
        return "decrypt failed"

    message = parse_text_message(decrypted_xml)
    await dispatch_message(message)
    return "success"


# ───────── 任务状态查询 ─────────


@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str) -> dict[str, Any]:
    """查询异步任务状态."""
    if task_queue is None:
        return {"error": "task queue not initialized"}
    info = task_queue.get_status(task_id)
    if info is None:
        return {"error": "task not found"}
    return {
        "task_id": info.task_id,
        "status": info.status.value,
        "error": info.error,
        "created_at": info.created_at.isoformat(),
        "finished_at": info.finished_at.isoformat() if info.finished_at else None,
    }
