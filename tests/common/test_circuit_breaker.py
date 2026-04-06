"""circuit_breaker 单元测试 — 熔断器状态机."""

import time
from unittest.mock import patch

import pytest

from src.common.circuit_breaker import CircuitBreaker, CircuitOpenError


def test_initial_state_is_closed() -> None:
    """新建的熔断器处于 closed 状态."""
    cb = CircuitBreaker("test")
    assert cb.is_closed
    assert not cb.is_open
    assert not cb.is_half_open


def test_check_passes_when_closed() -> None:
    """closed 状态下 check() 不抛异常."""
    cb = CircuitBreaker("test", failure_threshold=3)
    cb.check()  # 不应抛异常


def test_opens_after_threshold_failures() -> None:
    """连续失败达到阈值后进入 open 状态."""
    cb = CircuitBreaker("test", failure_threshold=3, recovery_seconds=60.0)

    cb.record_failure()
    cb.record_failure()
    assert cb.is_closed

    cb.record_failure()  # 第 3 次
    assert cb.is_open
    assert not cb.is_closed


def test_check_raises_when_open() -> None:
    """open 状态下 check() 抛出 CircuitOpenError."""
    cb = CircuitBreaker("test", failure_threshold=2, recovery_seconds=60.0)
    cb.record_failure()
    cb.record_failure()

    with pytest.raises(CircuitOpenError, match="test"):
        cb.check()


def test_half_open_after_recovery() -> None:
    """recovery_seconds 过后进入 half-open 状态."""
    cb = CircuitBreaker("test", failure_threshold=1, recovery_seconds=10.0)
    cb.record_failure()

    assert cb.is_open

    # 模拟时间过去
    with patch.object(time, "monotonic", return_value=time.monotonic() + 11):
        assert cb.is_half_open
        assert not cb.is_open
        cb.check()  # half-open 允许通过


def test_success_resets_to_closed() -> None:
    """record_success 将熔断器重置为 closed."""
    cb = CircuitBreaker("test", failure_threshold=2)
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open

    cb.record_success()
    assert cb.is_closed
    assert not cb.is_open


def test_partial_failures_reset_on_success() -> None:
    """未达阈值的失败在成功后清零."""
    cb = CircuitBreaker("test", failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    assert cb.is_closed  # 只有 1 次失败
