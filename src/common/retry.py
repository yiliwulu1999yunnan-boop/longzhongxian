"""通用异步指数退避重试."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from src.common.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


async def retry_with_backoff(
    func: Callable[..., Awaitable[T]],
    *args: object,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.5,
    retryable: Callable[[Exception], bool] | None = None,
    **kwargs: object,
) -> T:
    """带指数退避的异步重试.

    公式：delay = min(base_delay * 2^attempt, max_delay) + random(0, jitter)

    Args:
        func: 要重试的异步函数.
        *args: 传给 func 的位置参数.
        max_retries: 最大重试次数（不含首次尝试）.
        base_delay: 基础延迟（秒）.
        max_delay: 最大延迟（秒）.
        jitter: 随机抖动上限（秒）.
        retryable: 判断异常是否可重试的函数，默认所有异常都重试.
        **kwargs: 传给 func 的关键字参数.

    Returns:
        func 的返回值.

    Raises:
        最后一次重试失败的异常.
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc

            if attempt >= max_retries:
                break

            if retryable is not None and not retryable(exc):
                logger.info(
                    "retry_skipped_not_retryable",
                    func=func.__qualname__,
                    error=str(exc),
                )
                break

            delay = min(base_delay * (2**attempt), max_delay)
            delay += random.uniform(0, jitter)  # noqa: S311

            logger.warning(
                "retry_attempt",
                func=func.__qualname__,
                attempt=attempt + 1,
                max_retries=max_retries,
                delay=round(delay, 2),
                error=str(exc),
            )
            await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]
