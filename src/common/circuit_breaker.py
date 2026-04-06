"""通用熔断器 — 连续失败后自动暂停操作，防止雪崩."""

from __future__ import annotations

import time

from src.common.logger import get_logger

logger = get_logger(__name__)


class CircuitOpenError(Exception):
    """熔断器处于开启状态，拒绝执行操作."""

    def __init__(self, name: str, retry_in: float) -> None:
        self.name = name
        self.retry_in = retry_in
        super().__init__(f"熔断器 [{name}] 已开启，{retry_in:.1f}s 后重试")


class CircuitBreaker:
    """简单的三态熔断器：closed → open → half-open → closed.

    Args:
        name: 熔断器名称，用于日志标识.
        failure_threshold: 连续失败多少次触发熔断.
        recovery_seconds: 熔断持续时间（秒）.
    """

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 3,
        recovery_seconds: float = 120.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds

        self._failure_count = 0
        self._open_until = 0.0

    @property
    def is_closed(self) -> bool:
        """熔断器是否处于关闭（正常）状态."""
        return self._failure_count < self.failure_threshold

    @property
    def is_open(self) -> bool:
        """熔断器是否处于开启（拒绝请求）状态."""
        if self._failure_count < self.failure_threshold:
            return False
        return time.monotonic() < self._open_until

    @property
    def is_half_open(self) -> bool:
        """熔断器是否处于半开（允许试探）状态."""
        if self._failure_count < self.failure_threshold:
            return False
        return time.monotonic() >= self._open_until

    def check(self) -> None:
        """检查熔断器状态，open 时抛出 CircuitOpenError.

        Raises:
            CircuitOpenError: 熔断器处于 open 状态.
        """
        if self.is_open:
            retry_in = round(self._open_until - time.monotonic(), 1)
            logger.warning(
                "circuit_open",
                name=self.name,
                failures=self._failure_count,
                retry_in=retry_in,
            )
            raise CircuitOpenError(self.name, retry_in)

        if self.is_half_open:
            logger.info(
                "circuit_half_open",
                name=self.name,
                failures=self._failure_count,
            )

    def record_success(self) -> None:
        """记录一次成功，重置熔断器."""
        if self._failure_count > 0:
            logger.info(
                "circuit_closed",
                name=self.name,
                previous_failures=self._failure_count,
            )
        self._failure_count = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        """记录一次失败，必要时开启熔断."""
        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._open_until = time.monotonic() + self.recovery_seconds
            logger.warning(
                "circuit_opened",
                name=self.name,
                failures=self._failure_count,
                recovery_seconds=self.recovery_seconds,
            )
