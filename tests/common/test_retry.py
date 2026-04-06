"""retry 单元测试 — 指数退避重试."""

import pytest

from src.common.retry import retry_with_backoff


@pytest.mark.asyncio()
async def test_success_on_first_try() -> None:
    """首次成功不重试."""
    call_count = 0

    async def ok() -> str:
        nonlocal call_count
        call_count += 1
        return "done"

    result = await retry_with_backoff(ok, max_retries=3, base_delay=0.01)
    assert result == "done"
    assert call_count == 1


@pytest.mark.asyncio()
async def test_retries_on_failure_then_succeeds() -> None:
    """前两次失败，第三次成功."""
    call_count = 0

    async def flaky() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("timeout")
        return "recovered"

    result = await retry_with_backoff(flaky, max_retries=3, base_delay=0.01)
    assert result == "recovered"
    assert call_count == 3


@pytest.mark.asyncio()
async def test_raises_after_max_retries() -> None:
    """超过最大重试次数后抛出最后的异常."""
    call_count = 0

    async def always_fail() -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("permanent")

    with pytest.raises(ValueError, match="permanent"):
        await retry_with_backoff(always_fail, max_retries=2, base_delay=0.01)

    assert call_count == 3  # 1 initial + 2 retries


@pytest.mark.asyncio()
async def test_not_retryable_stops_immediately() -> None:
    """retryable 返回 False 时不重试."""
    call_count = 0

    async def fail_once() -> None:
        nonlocal call_count
        call_count += 1
        raise TypeError("not retryable")

    with pytest.raises(TypeError, match="not retryable"):
        await retry_with_backoff(
            fail_once,
            max_retries=3,
            base_delay=0.01,
            retryable=lambda exc: not isinstance(exc, TypeError),
        )

    assert call_count == 1


@pytest.mark.asyncio()
async def test_passes_args_and_kwargs() -> None:
    """正确传递位置参数和关键字参数."""

    async def add(a: int, *, b: int) -> int:
        return a + b

    result = await retry_with_backoff(add, 3, b=4, max_retries=0)
    assert result == 7
