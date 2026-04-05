"""指令分发器单元测试 — 覆盖各种指令格式."""

from __future__ import annotations

import pytest

from src.common.dispatcher import CommandType, classify_command, dispatch_message


class TestClassifyCommand:
    """classify_command 覆盖各种指令格式."""

    def test_screening_full(self) -> None:
        cmd, param = classify_command("筛选候选人")
        assert cmd == CommandType.SCREENING
        assert param == ""

    def test_screening_short(self) -> None:
        cmd, _ = classify_command("筛选")
        assert cmd == CommandType.SCREENING

    def test_greeting_send_numbers(self) -> None:
        cmd, _ = classify_command("发1、3")
        assert cmd == CommandType.GREETING

    def test_greeting_send_all(self) -> None:
        cmd, _ = classify_command("全发")
        assert cmd == CommandType.GREETING

    def test_greeting_send_with_comma(self) -> None:
        cmd, _ = classify_command("发1,3")
        assert cmd == CommandType.GREETING

    def test_greeting_send_with_space(self) -> None:
        cmd, _ = classify_command("发 1 3")
        assert cmd == CommandType.GREETING

    def test_analyze_candidate(self) -> None:
        cmd, param = classify_command("分析候选人张三")
        assert cmd == CommandType.ANALYZE
        assert param == "张三"

    def test_analyze_candidate_with_space(self) -> None:
        cmd, param = classify_command("分析候选人 李四")
        assert cmd == CommandType.ANALYZE
        assert param == "李四"

    def test_unknown(self) -> None:
        cmd, _ = classify_command("你好")
        assert cmd == CommandType.UNKNOWN

    def test_empty(self) -> None:
        cmd, _ = classify_command("")
        assert cmd == CommandType.SKIP_EMPTY


class TestDispatchMessage:
    """dispatch_message 集成分发测试."""

    @pytest.mark.asyncio
    async def test_dispatch_screening(self) -> None:
        result = await dispatch_message({
            "msg_type": "text",
            "content": "筛选候选人",
            "from_user": "user_001",
        })
        assert result == CommandType.SCREENING

    @pytest.mark.asyncio
    async def test_dispatch_greeting(self) -> None:
        result = await dispatch_message({
            "msg_type": "text",
            "content": "发1、3",
            "from_user": "user_001",
        })
        assert result == CommandType.GREETING

    @pytest.mark.asyncio
    async def test_dispatch_analyze(self) -> None:
        result = await dispatch_message({
            "msg_type": "text",
            "content": "分析候选人张三",
            "from_user": "user_001",
        })
        assert result == CommandType.ANALYZE

    @pytest.mark.asyncio
    async def test_dispatch_non_text(self) -> None:
        result = await dispatch_message({
            "msg_type": "image",
            "content": "",
            "from_user": "user_001",
        })
        assert result == CommandType.SKIP_NON_TEXT

    @pytest.mark.asyncio
    async def test_dispatch_empty_content(self) -> None:
        result = await dispatch_message({
            "msg_type": "text",
            "content": "",
            "from_user": "user_001",
        })
        assert result == CommandType.SKIP_EMPTY

    @pytest.mark.asyncio
    async def test_dispatch_unknown(self) -> None:
        result = await dispatch_message({
            "msg_type": "text",
            "content": "今天天气怎么样",
            "from_user": "user_001",
        })
        assert result == CommandType.UNKNOWN
