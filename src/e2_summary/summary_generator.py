"""LLM 沟通汇总生成器 — 聊天记录 + 简历数据 → 结构化沟通汇总."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI, APIConnectionError, APITimeoutError

from src.common.config import get_settings
from src.common.logger import get_logger
from src.e2_summary.chat_scraper import ChatMessage

logger = get_logger(__name__)

_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MAX_RETRIES = 2

# 聊天记录最大 token 估算（中文 ~2 字符/token，留给 prompt + 输出的余量）
_MAX_CHAT_CHARS = 8000


# ───────── 数据结构 ─────────


@dataclass
class SummaryResult:
    """结构化沟通汇总."""

    key_info: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    interview_recommendation: str = ""  # 建议约面 / 再观察 / 不建议
    raw_output: str = ""
    error: str | None = None


# ───────── 候选人名称模糊匹配 ─────────


def fuzzy_match_candidate(
    query: str,
    candidates: list[dict[str, str]],
) -> dict[str, str] | None:
    """模糊匹配候选人姓名.

    Boss 直聘脱敏姓名只有部分字符（如 "张*"），店长输入可能是全名 "张三"。
    匹配策略：
    1. 精确匹配（脱敏名 == 查询名）
    2. 查询名以脱敏名的首字开头且长度兼容
    3. 脱敏名首字与查询名首字相同

    Args:
        query: 店长输入的候选人名称.
        candidates: 候选人列表，每项需有 "name" 键.

    Returns:
        匹配到的候选人 dict，未找到返回 None.
    """
    query = query.strip()
    if not query or not candidates:
        return None

    # 精确匹配
    for c in candidates:
        if c.get("name", "") == query:
            return c

    # 首字匹配 + 脱敏名包含 *
    for c in candidates:
        name = c.get("name", "")
        if not name:
            continue
        # 脱敏名首字与查询首字相同
        if name[0] == query[0]:
            # 如果脱敏名包含 * 号，视为模糊匹配成功
            if "*" in name:
                return c
            # 如果脱敏名与查询名长度一致
            if len(name) == len(query):
                return c

    return None


# ───────── 聊天记录格式化 ─────────


def format_chat_messages(messages: list[ChatMessage]) -> str:
    """将聊天消息列表格式化为 LLM 可读的文本.

    超过 _MAX_CHAT_CHARS 时截断较早的消息，保留最新对话。
    """
    lines: list[str] = []
    for msg in messages:
        if msg.msg_type != "text":
            continue
        role = "Boss" if msg.is_from_boss else "候选人"
        time_str = msg.timestamp.strftime("%m-%d %H:%M")
        lines.append(f"[{time_str}] {role}: {msg.content}")

    text = "\n".join(lines)
    if len(text) > _MAX_CHAT_CHARS:
        # 保留最新的消息
        text = text[-_MAX_CHAT_CHARS:]
        # 从第一个完整行开始
        first_newline = text.find("\n")
        if first_newline > 0:
            text = "...(较早消息已省略)\n" + text[first_newline + 1:]
    return text


# ───────── Prompt ─────────


_SYSTEM_PROMPT = """你是一位资深的招聘助手，帮助店长分析与候选人的沟通记录。

请根据提供的聊天记录和候选人简历信息，生成一份结构化的沟通汇总。

请严格以如下 JSON 格式返回（不要包含其他内容）：
{
  "key_info": ["关键信息1", "关键信息2"],
  "risks": ["风险点1", "风险点2"],
  "highlights": ["亮点1", "亮点2"],
  "interview_recommendation": "建议约面" 或 "再观察" 或 "不建议"
}

分析要点：
- key_info：提取候选人在聊天中透露的关键信息（期望薪资、到岗时间、离职原因等）
- risks：发现的风险信号（频繁跳槽、态度消极、要求过高等）
- highlights：积极信号（主动询问工作内容、表达热情、经验匹配等）
- interview_recommendation：综合判断是否建议约面试
"""


def _build_user_prompt(
    chat_text: str,
    resume_info: str,
) -> str:
    """构建用户侧 prompt."""
    parts = []
    if resume_info:
        parts.append(f"## 候选人简历信息\n{resume_info}")
    parts.append(f"## 沟通记录\n{chat_text}")
    return "\n\n".join(parts)


# ───────── LLM 响应解析 ─────────


def parse_summary_response(raw_output: str) -> SummaryResult:
    """解析 LLM 返回的 JSON 为 SummaryResult."""
    text = raw_output.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1]
        text = text.split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1]
        text = text.split("```", 1)[0]

    try:
        data: dict[str, Any] = json.loads(text.strip())
    except json.JSONDecodeError as exc:
        return SummaryResult(
            raw_output=raw_output,
            error=f"JSON 解析失败: {exc}",
        )

    return SummaryResult(
        key_info=data.get("key_info", []),
        risks=data.get("risks", []),
        highlights=data.get("highlights", []),
        interview_recommendation=data.get("interview_recommendation", ""),
        raw_output=raw_output,
    )


# ───────── 汇总格式化 ─────────


def format_summary_markdown(
    candidate_name: str,
    result: SummaryResult,
) -> str:
    """将 SummaryResult 格式化为企业微信 Markdown 消息."""
    lines = [f"## 沟通汇总 — {candidate_name}"]

    if result.error:
        lines.append(f"\n⚠️ 汇总生成失败: {result.error}")
        return "\n".join(lines)

    if result.key_info:
        lines.append("\n### 关键信息")
        for info in result.key_info:
            lines.append(f"- {info}")

    if result.highlights:
        lines.append("\n### 亮点")
        for hl in result.highlights:
            lines.append(f"- {hl}")

    if result.risks:
        lines.append("\n### ⚠️ 风险点")
        for risk in result.risks:
            lines.append(f"- {risk}")

    if result.interview_recommendation:
        lines.append(f"\n**约面建议：{result.interview_recommendation}**")

    return "\n".join(lines)


# ───────── 汇总生成器 ─────────


class SummaryGenerator:
    """LLM 沟通汇总生成器."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = _DEFAULT_MODEL,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(
            api_key=api_key or settings.deepseek_api_key,
            base_url=base_url or settings.deepseek_base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._model = model

    async def generate(
        self,
        messages: list[ChatMessage],
        resume_info: str = "",
    ) -> SummaryResult:
        """生成沟通汇总.

        Args:
            messages: 聊天消息列表.
            resume_info: 候选人简历/评分信息文本.

        Returns:
            SummaryResult 结构化汇总结果.
        """
        chat_text = format_chat_messages(messages)
        if not chat_text.strip():
            return SummaryResult(error="无有效聊天记录")

        user_prompt = _build_user_prompt(chat_text, resume_info)

        logger.info("summary_llm_start", model=self._model, chat_chars=len(chat_text))

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
            )
        except (APITimeoutError, APIConnectionError) as exc:
            logger.warning("summary_llm_api_failed", error=str(exc))
            return SummaryResult(error=f"API 调用失败: {exc}")
        except Exception as exc:
            logger.error("summary_llm_unknown_error", error=str(exc), exc_info=True)
            return SummaryResult(error=f"未知错误: {exc}")

        raw_output = response.choices[0].message.content or ""
        result = parse_summary_response(raw_output)
        if result.error:
            logger.warning("summary_llm_parse_failed", error=result.error)
        else:
            logger.info("summary_llm_done", recommendation=result.interview_recommendation)
        return result
