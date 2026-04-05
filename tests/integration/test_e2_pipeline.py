"""E2 流程端到端集成测试 — 全 mock，验证 pipeline 编排逻辑."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.e2_summary.chat_scraper import ChatMessage
from src.e2_summary.pipeline import E2PipelineError, E2PipelineResult, run_e2_pipeline
from src.e2_summary.summary_generator import SummaryGenerator, SummaryResult


def _make_messages() -> list[ChatMessage]:
    """构造测试用聊天消息."""
    return [
        ChatMessage(
            message_id="1",
            sender_name="Boss",
            sender_uid="boss1",
            content="你好，看到你的简历很不错",
            timestamp=datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc),
            is_from_boss=True,
        ),
        ChatMessage(
            message_id="2",
            sender_name="张三",
            sender_uid="geek1",
            content="谢谢，我对这个岗位很感兴趣，期望薪资5000左右",
            timestamp=datetime(2026, 4, 1, 10, 1, tzinfo=timezone.utc),
            is_from_boss=False,
        ),
        ChatMessage(
            message_id="3",
            sender_name="Boss",
            sender_uid="boss1",
            content="好的，方便这周来面试吗？",
            timestamp=datetime(2026, 4, 1, 10, 2, tzinfo=timezone.utc),
            is_from_boss=True,
        ),
    ]


def _make_candidates() -> list[dict[str, str]]:
    """构造测试用候选人列表."""
    return [
        {"name": "张*", "encrypt_geek_id": "enc_001"},
        {"name": "李*", "encrypt_geek_id": "enc_002"},
        {"name": "王**", "encrypt_geek_id": "enc_003"},
    ]


def _make_summary_result() -> SummaryResult:
    """构造测试用汇总结果."""
    return SummaryResult(
        key_info=["期望薪资5000", "本周可面试"],
        risks=["无明显风险"],
        highlights=["态度积极", "主动表达兴趣"],
        interview_recommendation="建议约面",
    )


class TestE2Pipeline:
    """E2 端到端流程集成测试."""

    @pytest.mark.asyncio
    async def test_full_pipeline_success(self) -> None:
        """完整流程：匹配候选人 → 生成汇总 → 推送成功."""
        mock_channel = AsyncMock()
        mock_generator = AsyncMock(spec=SummaryGenerator)
        mock_generator.generate = AsyncMock(return_value=_make_summary_result())

        result = await run_e2_pipeline(
            candidate_query="张三",
            candidates=_make_candidates(),
            chat_messages=_make_messages(),
            push_channel=mock_channel,
            push_user_id="wechat_user_001",
            generator=mock_generator,
            resume_info="3年餐饮经验",
        )

        assert isinstance(result, E2PipelineResult)
        assert result.candidate_name == "张*"
        assert result.summary.error is None
        assert result.summary.interview_recommendation == "建议约面"
        assert result.pushed is True
        assert "沟通汇总" in result.markdown
        assert "关键信息" in result.markdown
        mock_channel.send_markdown.assert_called_once()
        mock_generator.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_candidate_not_found(self) -> None:
        """候选人未找到应抛出 E2PipelineError."""
        mock_channel = AsyncMock()

        with pytest.raises(E2PipelineError, match="未找到匹配的候选人"):
            await run_e2_pipeline(
                candidate_query="赵六",
                candidates=_make_candidates(),
                chat_messages=_make_messages(),
                push_channel=mock_channel,
                push_user_id="wechat_user_001",
            )

    @pytest.mark.asyncio
    async def test_push_failure_graceful(self) -> None:
        """推送失败不应导致整个流程失败."""
        mock_channel = AsyncMock()
        mock_channel.send_markdown = AsyncMock(side_effect=Exception("网络超时"))
        mock_generator = AsyncMock(spec=SummaryGenerator)
        mock_generator.generate = AsyncMock(return_value=_make_summary_result())

        result = await run_e2_pipeline(
            candidate_query="张三",
            candidates=_make_candidates(),
            chat_messages=_make_messages(),
            push_channel=mock_channel,
            push_user_id="wechat_user_001",
            generator=mock_generator,
        )

        assert result.pushed is False
        assert result.summary.error is None
        assert result.candidate_name == "张*"

    @pytest.mark.asyncio
    async def test_llm_error_propagated(self) -> None:
        """LLM 生成失败时，结果中应包含 error."""
        mock_channel = AsyncMock()
        error_result = SummaryResult(error="API 调用失败: timeout")
        mock_generator = AsyncMock(spec=SummaryGenerator)
        mock_generator.generate = AsyncMock(return_value=error_result)

        result = await run_e2_pipeline(
            candidate_query="张三",
            candidates=_make_candidates(),
            chat_messages=_make_messages(),
            push_channel=mock_channel,
            push_user_id="wechat_user_001",
            generator=mock_generator,
        )

        assert result.summary.error is not None
        assert "汇总生成失败" in result.markdown
        # 即使生成失败，也会推送错误报告
        assert result.pushed is True

    @pytest.mark.asyncio
    async def test_masked_name_fuzzy_match(self) -> None:
        """脱敏名模糊匹配验证."""
        mock_channel = AsyncMock()
        mock_generator = AsyncMock(spec=SummaryGenerator)
        mock_generator.generate = AsyncMock(return_value=_make_summary_result())

        # "王五六" 应匹配 "王**"
        result = await run_e2_pipeline(
            candidate_query="王五六",
            candidates=_make_candidates(),
            chat_messages=_make_messages(),
            push_channel=mock_channel,
            push_user_id="wechat_user_001",
            generator=mock_generator,
        )

        assert result.candidate_name == "王**"
