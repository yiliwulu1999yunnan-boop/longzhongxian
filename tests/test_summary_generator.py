"""沟通汇总生成器单元测试 — 名称模糊匹配 + LLM 汇总结构验证."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.e2_summary.chat_scraper import ChatMessage
from src.e2_summary.summary_generator import (
    SummaryGenerator,
    SummaryResult,
    format_chat_messages,
    format_summary_markdown,
    fuzzy_match_candidate,
    parse_summary_response,
)


# ───────── fuzzy_match_candidate ─────────


class TestFuzzyMatchCandidate:
    """候选人名称模糊匹配逻辑."""

    def test_exact_match(self) -> None:
        candidates = [{"name": "张三", "id": "1"}, {"name": "李四", "id": "2"}]
        result = fuzzy_match_candidate("张三", candidates)
        assert result is not None
        assert result["name"] == "张三"

    def test_masked_name_match(self) -> None:
        """脱敏名 '张*' 匹配查询 '张三'."""
        candidates = [{"name": "张*", "id": "1"}, {"name": "李*", "id": "2"}]
        result = fuzzy_match_candidate("张三", candidates)
        assert result is not None
        assert result["name"] == "张*"

    def test_masked_name_two_stars(self) -> None:
        """脱敏名 '张**' 匹配查询 '张三丰'."""
        candidates = [{"name": "张**", "id": "1"}]
        result = fuzzy_match_candidate("张三丰", candidates)
        assert result is not None
        assert result["name"] == "张**"

    def test_same_length_match(self) -> None:
        """无星号但首字相同且长度一致."""
        candidates = [{"name": "张三", "id": "1"}]
        result = fuzzy_match_candidate("张四", candidates)
        assert result is not None

    def test_no_match(self) -> None:
        candidates = [{"name": "张*", "id": "1"}, {"name": "李*", "id": "2"}]
        result = fuzzy_match_candidate("王五", candidates)
        assert result is None

    def test_empty_query(self) -> None:
        candidates = [{"name": "张*", "id": "1"}]
        result = fuzzy_match_candidate("", candidates)
        assert result is None

    def test_empty_candidates(self) -> None:
        result = fuzzy_match_candidate("张三", [])
        assert result is None

    def test_first_char_priority(self) -> None:
        """多个候选人首字相同时返回第一个匹配."""
        candidates = [
            {"name": "张*", "id": "1"},
            {"name": "张**", "id": "2"},
        ]
        result = fuzzy_match_candidate("张三", candidates)
        assert result is not None
        assert result["id"] == "1"


# ───────── format_chat_messages ─────────


class TestFormatChatMessages:
    """聊天记录格式化."""

    def _make_msg(
        self,
        content: str,
        is_from_boss: bool = False,
        msg_type: str = "text",
    ) -> ChatMessage:
        return ChatMessage(
            message_id="m1",
            sender_name="test",
            sender_uid="u1",
            content=content,
            timestamp=datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc),
            is_from_boss=is_from_boss,
            msg_type=msg_type,
        )

    def test_basic_format(self) -> None:
        msgs = [
            self._make_msg("你好", is_from_boss=True),
            self._make_msg("你好，我对这个岗位感兴趣"),
        ]
        result = format_chat_messages(msgs)
        assert "Boss: 你好" in result
        assert "候选人: 你好，我对这个岗位感兴趣" in result

    def test_skip_non_text(self) -> None:
        msgs = [
            self._make_msg("[图片]", msg_type="image"),
            self._make_msg("文本消息"),
        ]
        result = format_chat_messages(msgs)
        assert "[图片]" not in result
        assert "文本消息" in result

    def test_empty_messages(self) -> None:
        result = format_chat_messages([])
        assert result == ""

    def test_truncation(self) -> None:
        """超长记录应截断."""
        long_msg = self._make_msg("A" * 5000)
        msgs = [long_msg, long_msg, long_msg]
        result = format_chat_messages(msgs)
        assert len(result) <= 8100  # _MAX_CHAT_CHARS + 省略提示


# ───────── parse_summary_response ─────────


class TestParseSummaryResponse:
    """LLM 汇总响应解析."""

    def test_valid_json(self) -> None:
        raw = '{"key_info": ["期望薪资5000"], "risks": ["频繁跳槽"], "highlights": ["态度积极"], "interview_recommendation": "建议约面"}'
        result = parse_summary_response(raw)
        assert result.error is None
        assert result.key_info == ["期望薪资5000"]
        assert result.risks == ["频繁跳槽"]
        assert result.highlights == ["态度积极"]
        assert result.interview_recommendation == "建议约面"

    def test_json_in_code_block(self) -> None:
        raw = '```json\n{"key_info": ["info"], "risks": [], "highlights": [], "interview_recommendation": "再观察"}\n```'
        result = parse_summary_response(raw)
        assert result.error is None
        assert result.interview_recommendation == "再观察"

    def test_invalid_json(self) -> None:
        raw = "这不是 JSON"
        result = parse_summary_response(raw)
        assert result.error is not None
        assert "JSON 解析失败" in result.error

    def test_complete_structure(self) -> None:
        """验证输出包含完整结构：关键信息 + 风险 + 亮点 + 约面建议."""
        raw = '{"key_info": ["k1", "k2"], "risks": ["r1"], "highlights": ["h1"], "interview_recommendation": "建议约面"}'
        result = parse_summary_response(raw)
        assert result.error is None
        assert len(result.key_info) > 0
        assert len(result.risks) > 0
        assert len(result.highlights) > 0
        assert result.interview_recommendation in ("建议约面", "再观察", "不建议")


# ───────── format_summary_markdown ─────────


class TestFormatSummaryMarkdown:
    """汇总 Markdown 格式化."""

    def test_full_summary(self) -> None:
        result = SummaryResult(
            key_info=["期望薪资5000", "下周可到岗"],
            risks=["频繁跳槽"],
            highlights=["态度积极", "有相关经验"],
            interview_recommendation="建议约面",
        )
        md = format_summary_markdown("张*", result)
        assert "沟通汇总 — 张*" in md
        assert "关键信息" in md
        assert "期望薪资5000" in md
        assert "风险点" in md
        assert "亮点" in md
        assert "建议约面" in md

    def test_error_summary(self) -> None:
        result = SummaryResult(error="API 调用失败")
        md = format_summary_markdown("张*", result)
        assert "汇总生成失败" in md


# ───────── SummaryGenerator ─────────


class TestSummaryGenerator:
    """SummaryGenerator LLM 调用（全部 mock）."""

    @pytest.mark.asyncio
    async def test_generate_success(self) -> None:
        """mock LLM 返回正确 JSON，验证生成结果完整."""
        llm_response_json = (
            '{"key_info": ["期望薪资5000"], "risks": ["无"], '
            '"highlights": ["主动询问岗位"], "interview_recommendation": "建议约面"}'
        )
        mock_choice = MagicMock()
        mock_choice.message.content = llm_response_json
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch("src.e2_summary.summary_generator.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                deepseek_api_key="test-key",
                deepseek_base_url="https://test.api",
            )
            generator = SummaryGenerator(
                api_key="test-key", base_url="https://test.api"
            )
            generator._client = MagicMock()
            generator._client.chat = MagicMock()
            generator._client.chat.completions = MagicMock()
            generator._client.chat.completions.create = AsyncMock(
                return_value=mock_response
            )

            msgs = [
                ChatMessage(
                    message_id="1",
                    sender_name="Boss",
                    sender_uid="boss1",
                    content="你好，看到你的简历",
                    timestamp=datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc),
                    is_from_boss=True,
                ),
                ChatMessage(
                    message_id="2",
                    sender_name="张三",
                    sender_uid="geek1",
                    content="你好，我对这个岗位感兴趣",
                    timestamp=datetime(2026, 4, 1, 10, 1, tzinfo=timezone.utc),
                    is_from_boss=False,
                ),
            ]

            result = await generator.generate(msgs, resume_info="3年经验")

        assert result.error is None
        assert result.key_info == ["期望薪资5000"]
        assert result.highlights == ["主动询问岗位"]
        assert result.interview_recommendation == "建议约面"

    @pytest.mark.asyncio
    async def test_generate_empty_chat(self) -> None:
        """空聊天记录应返回错误."""
        with patch("src.e2_summary.summary_generator.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                deepseek_api_key="test-key",
                deepseek_base_url="https://test.api",
            )
            generator = SummaryGenerator(
                api_key="test-key", base_url="https://test.api"
            )
            result = await generator.generate([])

        assert result.error == "无有效聊天记录"

    @pytest.mark.asyncio
    async def test_generate_api_error(self) -> None:
        """LLM API 异常应返回降级结果."""
        from openai import APIConnectionError

        with patch("src.e2_summary.summary_generator.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                deepseek_api_key="test-key",
                deepseek_base_url="https://test.api",
            )
            generator = SummaryGenerator(
                api_key="test-key", base_url="https://test.api"
            )
            generator._client = MagicMock()
            generator._client.chat = MagicMock()
            generator._client.chat.completions = MagicMock()
            generator._client.chat.completions.create = AsyncMock(
                side_effect=APIConnectionError(request=MagicMock())
            )

            msgs = [
                ChatMessage(
                    message_id="1",
                    sender_name="Boss",
                    sender_uid="boss1",
                    content="你好",
                    timestamp=datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc),
                    is_from_boss=True,
                ),
            ]
            result = await generator.generate(msgs)

        assert result.error is not None
        assert "API 调用失败" in result.error
