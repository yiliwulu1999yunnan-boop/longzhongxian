"""Tests for common/task_queue — 任务提交、执行、并发互斥."""

import asyncio

import pytest

from src.common.task_queue import TaskQueue, TaskStatus


@pytest.mark.asyncio()
async def test_submit_and_complete() -> None:
    """提交任务后能正常执行并查询到结果."""
    queue = TaskQueue()

    async def dummy() -> str:
        return "done"

    task_id = await queue.submit(dummy)
    # 等待任务完成
    await asyncio.sleep(0.05)

    info = queue.get_status(task_id)
    assert info is not None
    assert info.status == TaskStatus.COMPLETED
    assert info.result == "done"
    assert info.finished_at is not None


@pytest.mark.asyncio()
async def test_task_failure_records_error() -> None:
    """任务抛出异常时状态为 FAILED，error 记录异常信息."""
    queue = TaskQueue()

    async def fail() -> None:
        raise ValueError("boom")

    task_id = await queue.submit(fail)
    await asyncio.sleep(0.05)

    info = queue.get_status(task_id)
    assert info is not None
    assert info.status == TaskStatus.FAILED
    assert info.error == "boom"


@pytest.mark.asyncio()
async def test_get_status_unknown_task() -> None:
    """查询不存在的任务返回 None."""
    queue = TaskQueue()
    assert queue.get_status("nonexistent") is None


@pytest.mark.asyncio()
async def test_account_mutex() -> None:
    """同一 account_id 的任务串行执行（互斥锁）."""
    queue = TaskQueue()
    order: list[str] = []

    async def step(name: str, delay: float) -> None:
        order.append(f"{name}_start")
        await asyncio.sleep(delay)
        order.append(f"{name}_end")

    # 提交两个同账号任务
    await queue.submit(step, "a", 0.05, account_id="boss1")
    await queue.submit(step, "b", 0.05, account_id="boss1")
    # 等待都完成
    await asyncio.sleep(0.3)

    # 同账号互斥：a 完全结束后 b 才开始
    assert order.index("a_end") < order.index("b_start")


@pytest.mark.asyncio()
async def test_different_accounts_parallel() -> None:
    """不同 account_id 的任务可以并行执行."""
    queue = TaskQueue()
    order: list[str] = []

    async def step(name: str) -> None:
        order.append(f"{name}_start")
        await asyncio.sleep(0.05)
        order.append(f"{name}_end")

    await queue.submit(step, "x", account_id="boss1")
    await queue.submit(step, "y", account_id="boss2")
    await asyncio.sleep(0.2)

    # 不同账号可以并行：两个 start 都在两个 end 之前
    assert order.index("x_start") < order.index("x_end")
    assert order.index("y_start") < order.index("y_end")
    # y 在 x 结束之前就开始了
    assert order.index("y_start") < order.index("x_end")


@pytest.mark.asyncio()
async def test_max_concurrency() -> None:
    """全局并发控制限制同时运行的任务数."""
    queue = TaskQueue(max_concurrency=1)
    order: list[str] = []

    async def step(name: str) -> None:
        order.append(f"{name}_start")
        await asyncio.sleep(0.05)
        order.append(f"{name}_end")

    await queue.submit(step, "p")
    await queue.submit(step, "q")
    await asyncio.sleep(0.3)

    # max_concurrency=1: p 结束后 q 才开始
    assert order.index("p_end") < order.index("q_start")


@pytest.mark.asyncio()
async def test_submit_with_kwargs() -> None:
    """提交任务时支持关键字参数."""
    queue = TaskQueue()

    async def greet(name: str, greeting: str = "hello") -> str:
        return f"{greeting} {name}"

    task_id = await queue.submit(greet, "world", greeting="hi")
    await asyncio.sleep(0.05)

    info = queue.get_status(task_id)
    assert info is not None
    assert info.result == "hi world"
