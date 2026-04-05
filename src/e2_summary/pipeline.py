"""E2 流程编排 — 分析候选人指令 → 匹配候选人 → 抓取聊天 → 生成汇总 → 推送."""

from __future__ import annotations

from dataclasses import dataclass

from src.c3_push.channel import PushChannel
from src.common.logger import get_logger
from src.e2_summary.chat_scraper import ChatMessage
from src.e2_summary.summary_generator import (
    SummaryGenerator,
    SummaryResult,
    format_summary_markdown,
    fuzzy_match_candidate,
)

logger = get_logger(__name__)


class E2PipelineError(Exception):
    """E2 流程执行错误."""


@dataclass
class E2PipelineResult:
    """E2 流程执行结果."""

    candidate_name: str
    summary: SummaryResult
    markdown: str
    pushed: bool = False


async def run_e2_pipeline(
    candidate_query: str,
    candidates: list[dict[str, str]],
    chat_messages: list[ChatMessage],
    push_channel: PushChannel,
    push_user_id: str,
    generator: SummaryGenerator | None = None,
    resume_info: str = "",
) -> E2PipelineResult:
    """执行 E2 沟通汇总全流程.

    Args:
        candidate_query: 店长输入的候选人名称（如 "张三"）.
        candidates: 候选人列表，每项需有 "name" 和 "encrypt_geek_id" 键.
        chat_messages: 已抓取的聊天消息列表.
        push_channel: 推送通道.
        push_user_id: 接收汇总的企业微信 userid.
        generator: LLM 汇总生成器（可选，默认新建）.
        resume_info: 候选人简历/评分信息文本.

    Returns:
        E2PipelineResult 包含汇总结果和推送状态.

    Raises:
        E2PipelineError: 候选人未找到.
    """
    # 1. 模糊匹配候选人
    matched = fuzzy_match_candidate(candidate_query, candidates)
    if matched is None:
        raise E2PipelineError(f"未找到匹配的候选人: {candidate_query}")

    candidate_name = matched.get("name", candidate_query)
    logger.info("e2_candidate_matched", query=candidate_query, matched=candidate_name)

    # 2. 生成 LLM 汇总
    if generator is None:
        generator = SummaryGenerator()

    summary = await generator.generate(chat_messages, resume_info)

    # 3. 格式化 Markdown
    markdown = format_summary_markdown(candidate_name, summary)

    # 4. 推送
    pushed = False
    try:
        await push_channel.send_markdown(push_user_id, markdown)
        pushed = True
        logger.info("e2_summary_pushed", candidate=candidate_name, user_id=push_user_id)
    except Exception as exc:
        logger.warning("e2_summary_push_failed", candidate=candidate_name, error=str(exc))

    return E2PipelineResult(
        candidate_name=candidate_name,
        summary=summary,
        markdown=markdown,
        pushed=pushed,
    )
