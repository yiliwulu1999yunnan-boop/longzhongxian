"""结构化日志测试 — 验证 JSON 格式输出."""

import json
import logging

from src.common.logger import get_logger, setup_logging


def test_logger_outputs_json(capfd: object) -> None:
    """验证 logger 输出符合 JSON 格式."""
    # 清除之前的 handler 避免干扰
    root = logging.getLogger()
    root.handlers.clear()

    setup_logging("DEBUG")
    logger = get_logger("test")
    logger.info("hello", key="value")

    # structlog → stdlib logging → StreamHandler(stdout) → capfd 捕获
    out = capfd.readouterr().out  # type: ignore[union-attr]
    lines = [line for line in out.strip().splitlines() if line.strip()]
    assert len(lines) > 0
    parsed = json.loads(lines[-1])
    assert parsed["event"] == "hello"
    assert parsed["key"] == "value"
    assert "timestamp" in parsed


def test_get_logger_returns_bound_logger() -> None:
    """验证 get_logger 返回的 logger 可正常调用."""
    setup_logging("INFO")
    logger = get_logger("mymodule")
    # 不抛异常即通过
    logger.info("test event")
