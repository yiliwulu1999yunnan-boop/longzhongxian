"""Tests for c2_scorer.llm_scorer — LLM 评估层."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.c2_scorer.llm_scorer import (
    LlmScorer,
    parse_llm_response,
    render_dimensions_detail,
    render_hard_rules_summary,
    render_prompt,
)
from src.c2_scorer.profile_loader import load_profile

_PROFILES_DIR = Path(__file__).resolve().parents[2] / "config" / "job_profiles"


@pytest.fixture()
def mian_dian_shi():
    return load_profile("mian_dian_shi", _PROFILES_DIR)


@pytest.fixture()
def wai_pin_chu_bei():
    return load_profile("wai_pin_chu_bei", _PROFILES_DIR)


# 模拟 LLM 正常返回的 JSON
_GOOD_LLM_RESPONSE = json.dumps(
    {
        "dimension_scores": [
            {"name": "能早起/手脚麻利", "score": 80, "reason": "有凌晨工作经历"},
            {"name": "吃苦耐劳", "score": 75, "reason": "做过体力劳动"},
            {"name": "抗压能力", "score": 70, "reason": "一般"},
            {"name": "服从管理与安排", "score": 85, "reason": "态度好"},
            {"name": "稳定性", "score": 60, "reason": "换过几次工作"},
            {"name": "求职动机", "score": 70, "reason": "想学面点"},
            {"name": "沟通表达能力", "score": 65, "reason": "简历较完整"},
            {"name": "相关经验", "score": 90, "reason": "3 年面点经验"},
        ],
        "weighted_total": 75.5,
        "verdict": "可以看看",
        "risks": ["近期换工作较频繁"],
        "highlights": ["有 3 年面点经验", "能接受凌晨上班"],
    },
    ensure_ascii=False,
)


# ───────── Prompt 渲染 ─────────


def test_render_hard_rules_summary(mian_dian_shi) -> None:
    """硬规则摘要包含关键信息."""
    summary = render_hard_rules_summary(mian_dian_shi)
    assert "20-40" in summary
    assert "不限" in summary  # education
    assert "凌晨" in summary


def test_render_hard_rules_with_experience(wai_pin_chu_bei) -> None:
    """有经验要求的岗位摘要包含年限."""
    summary = render_hard_rules_summary(wai_pin_chu_bei)
    assert "1" in summary
    assert "经验" in summary
    assert "调店" in summary


def test_render_dimensions_detail(mian_dian_shi) -> None:
    """维度详情包含所有维度名称和权重."""
    detail = render_dimensions_detail(mian_dian_shi)
    assert "能早起/手脚麻利" in detail
    assert "权重 15%" in detail
    assert "相关经验" in detail


def test_render_prompt_fills_placeholders(mian_dian_shi) -> None:
    """render_prompt 正确填入所有占位符."""
    system_prompt, user_content = render_prompt(mian_dian_shi, "候选人张三的简历")
    assert "{position_name}" not in system_prompt
    assert "{hard_rules_summary}" not in system_prompt
    assert "{dimensions_detail}" not in system_prompt
    assert "面点师" in system_prompt
    assert user_content == "候选人张三的简历"


# ───────── 响应解析 ─────────


def test_parse_good_response(mian_dian_shi) -> None:
    """正常 JSON 响应解析出完整结果."""
    result = parse_llm_response(_GOOD_LLM_RESPONSE, mian_dian_shi)
    assert result.error is None
    assert len(result.dimension_scores) == 8
    assert result.weighted_total == 75.5
    assert result.verdict == "可以看看"
    assert len(result.risks) == 1
    assert len(result.highlights) == 2


def test_parse_response_with_code_block(mian_dian_shi) -> None:
    """LLM 返回被 markdown code block 包裹的 JSON."""
    wrapped = f"```json\n{_GOOD_LLM_RESPONSE}\n```"
    result = parse_llm_response(wrapped, mian_dian_shi)
    assert result.error is None
    assert result.verdict == "可以看看"


def test_parse_response_with_plain_code_block(mian_dian_shi) -> None:
    """LLM 返回被 ``` 包裹（无 json 标签）的 JSON."""
    wrapped = f"```\n{_GOOD_LLM_RESPONSE}\n```"
    result = parse_llm_response(wrapped, mian_dian_shi)
    assert result.error is None
    assert result.verdict == "可以看看"


def test_parse_invalid_json(mian_dian_shi) -> None:
    """非法 JSON → 返回带 error 的降级结果."""
    result = parse_llm_response("这不是 JSON", mian_dian_shi)
    assert result.error is not None
    assert "JSON 解析失败" in result.error
    assert result.raw_output == "这不是 JSON"


def test_parse_empty_response(mian_dian_shi) -> None:
    """空响应 → 返回带 error 的降级结果."""
    result = parse_llm_response("", mian_dian_shi)
    assert result.error is not None


def test_parse_partial_json(mian_dian_shi) -> None:
    """JSON 缺少部分字段 → 缺失字段用默认值."""
    partial = json.dumps({"verdict": "推荐沟通"})
    result = parse_llm_response(partial, mian_dian_shi)
    assert result.error is None
    assert result.verdict == "推荐沟通"
    assert result.dimension_scores == []
    assert result.weighted_total == 0.0


def test_parse_dimension_weight_mapping(mian_dian_shi) -> None:
    """解析时正确从 profile 映射维度权重."""
    result = parse_llm_response(_GOOD_LLM_RESPONSE, mian_dian_shi)
    early_bird = next(
        d for d in result.dimension_scores if d.name == "能早起/手脚麻利"
    )
    assert early_bird.weight == 15
    assert early_bird.score == 80


# ───────── LlmScorer API 调用 ─────────


@pytest.mark.asyncio()
async def test_evaluate_success(mian_dian_shi) -> None:
    """正常调用 LLM API 返回解析后的结果."""
    mock_choice = MagicMock()
    mock_choice.message.content = _GOOD_LLM_RESPONSE
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch("src.c2_scorer.llm_scorer.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_cls.return_value = mock_client

        scorer = LlmScorer(api_key="test", base_url="http://test")
        result = await scorer.evaluate(mian_dian_shi, "候选人简历内容")

    assert result.error is None
    assert result.verdict == "可以看看"
    assert len(result.dimension_scores) == 8

    # 验证 API 调用参数
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "deepseek-chat"
    assert len(call_kwargs["messages"]) == 2
    assert "面点师" in call_kwargs["messages"][0]["content"]
    assert "候选人简历内容" in call_kwargs["messages"][1]["content"]


@pytest.mark.asyncio()
async def test_evaluate_timeout_degrades(mian_dian_shi) -> None:
    """API 超时 → 返回带 error 的降级结果."""
    from openai import APITimeoutError

    with patch("src.c2_scorer.llm_scorer.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = APITimeoutError(
            request=MagicMock()
        )
        mock_cls.return_value = mock_client

        scorer = LlmScorer(api_key="test", base_url="http://test")
        result = await scorer.evaluate(mian_dian_shi, "简历")

    assert result.error is not None
    assert "API 调用失败" in result.error


@pytest.mark.asyncio()
async def test_evaluate_connection_error_degrades(mian_dian_shi) -> None:
    """API 连接错误 → 返回带 error 的降级结果."""
    from openai import APIConnectionError

    with patch("src.c2_scorer.llm_scorer.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = APIConnectionError(
            request=MagicMock()
        )
        mock_cls.return_value = mock_client

        scorer = LlmScorer(api_key="test", base_url="http://test")
        result = await scorer.evaluate(mian_dian_shi, "简历")

    assert result.error is not None


@pytest.mark.asyncio()
async def test_evaluate_llm_returns_bad_json(mian_dian_shi) -> None:
    """LLM 返回非法 JSON → 降级结果带 error 但不抛异常."""
    mock_choice = MagicMock()
    mock_choice.message.content = "抱歉我无法评估这个候选人"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch("src.c2_scorer.llm_scorer.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_cls.return_value = mock_client

        scorer = LlmScorer(api_key="test", base_url="http://test")
        result = await scorer.evaluate(mian_dian_shi, "简历")

    assert result.error is not None
    assert "JSON 解析失败" in result.error
    assert result.raw_output == "抱歉我无法评估这个候选人"
