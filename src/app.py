"""FastAPI 应用入口 — 健康检查 + 企业微信回调路由 + 异步任务调度."""

import os
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Query, Request
from fastapi.responses import PlainTextResponse

from src.c3_push.wechat_callback import (
    CallbackCryptoError,
    WechatCallbackCrypto,
    parse_text_message,
)
from src.common.config import get_settings
from src.common.dispatcher import (
    dispatch_message,
    register_analyze_callback,
    register_greeting_callback,
    register_screening_callback,
)
from src.common.logger import get_logger, setup_logging
from src.common.task_queue import TaskQueue

logger = get_logger(__name__)

# 全局任务队列（在 lifespan 中初始化）
task_queue: TaskQueue | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动时初始化全局资源."""
    global task_queue  # noqa: PLW0603
    settings = get_settings()
    setup_logging(settings.log_level)

    # P0-2: 强制单 Worker — 多 worker 下并发抓取/打招呼会触发风控
    workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
    if workers > 1:
        logger.error("multi_worker_rejected", workers=workers)
        sys.exit("致命错误: 本系统必须以单 worker 运行，检测到 WEB_CONCURRENCY=%d" % workers)

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
    logger.info("app_stopped")


app = FastAPI(title="笼中仙 AI 招聘助手", version="0.1.0", lifespan=lifespan)


# ───────── 占位任务函数（养号期不跑真实 pipeline） ─────────


async def _run_screening_task(from_user: str) -> str:
    """筛选任务占位 — 后续接入 run_screening()."""
    logger.info("screening_task_running", from_user=from_user)
    return "screening_placeholder"


async def _run_greeting_task(from_user: str, content: str) -> str:
    """打招呼任务占位 — 后续接入 run_c4_pipeline()."""
    logger.info("greeting_task_running", from_user=from_user, content=content)
    return "greeting_placeholder"


async def _run_analyze_task(from_user: str, candidate_name: str) -> str:
    """分析任务占位 — 后续接入 run_e2_pipeline()."""
    logger.info("analyze_task_running", from_user=from_user, candidate=candidate_name)
    return "analyze_placeholder"


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
