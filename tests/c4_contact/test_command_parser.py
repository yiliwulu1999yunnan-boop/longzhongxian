"""Tests for c4_contact/command_parser — 店长打招呼指令解析."""

import pytest

from src.c4_contact.command_parser import (
    is_greeting_command,
    parse_greeting_command,
)

# 模拟 ReportResult.number_mapping: 编号 → candidate_id
_MAPPING: dict[int, int] = {1: 101, 2: 102, 3: 103}


# ───────── 正常解析：各种格式 ─────────


def test_parse_chinese_dunhao() -> None:
    """中文顿号分隔：发1、3."""
    result = parse_greeting_command("发1、3", _MAPPING)
    assert result.ok
    assert result.candidate_ids == [101, 103]


def test_parse_chinese_comma() -> None:
    """中文逗号分隔：发1，3."""
    result = parse_greeting_command("发1，3", _MAPPING)
    assert result.ok
    assert result.candidate_ids == [101, 103]


def test_parse_english_comma() -> None:
    """英文逗号分隔：发1,3."""
    result = parse_greeting_command("发1,3", _MAPPING)
    assert result.ok
    assert result.candidate_ids == [101, 103]


def test_parse_space_separated() -> None:
    """空格分隔：发 1 3."""
    result = parse_greeting_command("发 1 3", _MAPPING)
    assert result.ok
    assert result.candidate_ids == [101, 103]


def test_parse_single_number() -> None:
    """单个编号：发2."""
    result = parse_greeting_command("发2", _MAPPING)
    assert result.ok
    assert result.candidate_ids == [102]


def test_parse_all_numbers() -> None:
    """所有编号：发1、2、3."""
    result = parse_greeting_command("发1、2、3", _MAPPING)
    assert result.ok
    assert sorted(result.candidate_ids) == [101, 102, 103]


def test_parse_with_extra_spaces() -> None:
    """带多余空格：发 1 、 3."""
    result = parse_greeting_command("  发 1 、 3  ", _MAPPING)
    assert result.ok
    assert result.candidate_ids == [101, 103]


def test_parse_mixed_separators() -> None:
    """混合分隔符：发1,2、3."""
    result = parse_greeting_command("发1,2、3", _MAPPING)
    assert result.ok
    assert result.candidate_ids == [101, 102, 103]


def test_parse_traditional_fa() -> None:
    """繁体"發"字：發1、3."""
    result = parse_greeting_command("發1、3", _MAPPING)
    assert result.ok
    assert result.candidate_ids == [101, 103]


def test_parse_dedup_numbers() -> None:
    """重复编号去重：发1、1、3."""
    result = parse_greeting_command("发1、1、3", _MAPPING)
    assert result.ok
    assert result.candidate_ids == [101, 103]


# ───────── "全发" 指令 ─────────


def test_parse_send_all_quanfa() -> None:
    """全发."""
    result = parse_greeting_command("全发", _MAPPING)
    assert result.ok
    assert result.is_send_all
    assert sorted(result.candidate_ids) == [101, 102, 103]


def test_parse_send_all_quanbu() -> None:
    """全部."""
    result = parse_greeting_command("全部", _MAPPING)
    assert result.ok
    assert result.is_send_all


def test_parse_fa_quanfa() -> None:
    """发全发."""
    result = parse_greeting_command("发全发", _MAPPING)
    assert result.ok
    assert result.is_send_all


def test_parse_fa_quanbu() -> None:
    """发全部."""
    result = parse_greeting_command("发全部", _MAPPING)
    assert result.ok
    assert result.is_send_all


def test_parse_all_english() -> None:
    """all (英文)."""
    result = parse_greeting_command("all", _MAPPING)
    assert result.ok
    assert result.is_send_all


def test_parse_send_all_empty_mapping() -> None:
    """全发但没有推荐候选人."""
    result = parse_greeting_command("全发", {})
    assert not result.ok
    assert "没有推荐候选人" in result.error


# ───────── 错误处理 ─────────


def test_parse_empty_text() -> None:
    """空文本."""
    result = parse_greeting_command("", _MAPPING)
    assert not result.ok
    assert "指令为空" in result.error


def test_parse_unrecognized_command() -> None:
    """无法识别的指令."""
    result = parse_greeting_command("你好", _MAPPING)
    assert not result.ok
    assert "无法识别" in result.error


def test_parse_out_of_range_number() -> None:
    """编号超范围."""
    result = parse_greeting_command("发5", _MAPPING)
    assert not result.ok
    assert "超出范围" in result.error
    assert "5" in result.error


def test_parse_partial_out_of_range() -> None:
    """部分编号超范围：发1、5."""
    result = parse_greeting_command("发1、5", _MAPPING)
    assert not result.ok
    assert "超出范围" in result.error


def test_parse_invalid_content() -> None:
    """包含非数字内容：发abc."""
    result = parse_greeting_command("发abc", _MAPPING)
    assert not result.ok
    assert "无法识别的内容" in result.error


def test_parse_fa_only() -> None:
    """只有"发"字没有编号."""
    result = parse_greeting_command("发", _MAPPING)
    assert not result.ok
    assert result.error  # 应有错误信息


# ───────── is_greeting_command 快速判断 ─────────


@pytest.mark.parametrize("text", [
    "发1、3", "发1,3", "发 1 3", "全发", "全部", "all", "發1",
])
def test_is_greeting_command_true(text: str) -> None:
    """是打招呼指令."""
    assert is_greeting_command(text)


@pytest.mark.parametrize("text", [
    "你好", "查看报告", "", "  ", "开始筛选",
])
def test_is_greeting_command_false(text: str) -> None:
    """不是打招呼指令."""
    assert not is_greeting_command(text)
