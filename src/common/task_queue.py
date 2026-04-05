"""异步任务队列 — 基于 asyncio 的简易调度器（V1 单机，不引入 Celery）."""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable

from src.common.logger import get_logger

logger = get_logger(__name__)


class TaskStatus(str, Enum):
    """任务状态."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskInfo:
    """任务元信息."""

    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None


class TaskQueue:
    """基于 asyncio 的简易任务队列.

    支持：
    - 任务提交与状态查询
    - 同一 Boss 账号互斥锁（防止并发操作同一浏览器会话）
    - 最大并发控制
    """

    def __init__(self, max_concurrency: int = 3) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._account_locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[str, TaskInfo] = {}

    def _get_account_lock(self, account_id: str) -> asyncio.Lock:
        """获取指定 Boss 账号的互斥锁（懒创建）."""
        if account_id not in self._account_locks:
            self._account_locks[account_id] = asyncio.Lock()
        return self._account_locks[account_id]

    async def submit(
        self,
        coro_func: Callable[..., Awaitable[Any]],
        *args: Any,
        account_id: str = "",
        **kwargs: Any,
    ) -> str:
        """提交异步任务，返回 task_id.

        Args:
            coro_func: 异步可调用对象
            *args: 传给 coro_func 的位置参数
            account_id: Boss 账号 ID，同一账号的任务互斥执行
            **kwargs: 传给 coro_func 的关键字参数

        Returns:
            任务 ID（UUID）
        """
        task_id = uuid.uuid4().hex[:12]
        info = TaskInfo(task_id=task_id)
        self._tasks[task_id] = info

        asyncio.create_task(self._run(task_id, coro_func, args, kwargs, account_id))
        logger.info("task_submitted", task_id=task_id, account_id=account_id)
        return task_id

    async def _run(
        self,
        task_id: str,
        coro_func: Callable[..., Awaitable[Any]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        account_id: str,
    ) -> None:
        """执行任务，带全局并发控制 + 账号互斥锁."""
        info = self._tasks[task_id]

        async with self._semaphore:
            if account_id:
                lock = self._get_account_lock(account_id)
                async with lock:
                    await self._execute(info, coro_func, args, kwargs)
            else:
                await self._execute(info, coro_func, args, kwargs)

    async def _execute(
        self,
        info: TaskInfo,
        coro_func: Callable[..., Awaitable[Any]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        """实际执行任务并更新状态."""
        info.status = TaskStatus.RUNNING
        logger.info("task_running", task_id=info.task_id)
        try:
            info.result = await coro_func(*args, **kwargs)
            info.status = TaskStatus.COMPLETED
            logger.info("task_completed", task_id=info.task_id)
        except Exception as exc:
            info.status = TaskStatus.FAILED
            info.error = str(exc)
            logger.error("task_failed", task_id=info.task_id, error=str(exc))
        finally:
            info.finished_at = datetime.now(timezone.utc)

    def get_status(self, task_id: str) -> TaskInfo | None:
        """查询任务状态，不存在返回 None."""
        return self._tasks.get(task_id)
