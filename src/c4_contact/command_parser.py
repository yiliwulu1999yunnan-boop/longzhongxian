"""店长回复指令解析 — 从企业微信文本中提取打招呼目标候选人编号."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.common.logger import get_logger

logger = get_logger(__name__)

# 匹配"发"字开头的打招呼指令
_PATTERN_SEND = re.compile(r"^[发發]\s*(.+)$", re.DOTALL)
# 匹配"全发"/"全部"/"all"
_PATTERN_ALL = re.compile(r"^(全发|全部|all)$", re.IGNORECASE)
# 分隔符：中文顿号、中英文逗号、空格
_SEPARATOR = re.compile(r"[、，,\s]+")


@dataclass
class ParsedCommand:
    """指令解析结果."""

    candidate_ids: list[int] = field(default_factory=list)
    is_send_all: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        """解析是否成功."""
        return not self.error and (self.is_send_all or len(self.candidate_ids) > 0)


def parse_greeting_command(
    text: str,
    number_mapping: dict[int, int],
) -> ParsedCommand:
    """解析店长回复的打招呼指令.

    支持格式：
    - "发1、3"  "发1,3"  "发 1 3"  "发1，3"
    - "全发"  "全部"  "all"

    Args:
        text: 店长回复的原始文本.
        number_mapping: 编号 → candidate_id 映射（来自 ReportResult）.

    Returns:
        ParsedCommand 包含解析出的 candidate_id 列表或错误信息.
    """
    text = text.strip()
    if not text:
        return ParsedCommand(error="指令为空")

    # 先检查是否为"全发"指令（不需要"发"字前缀）
    if _PATTERN_ALL.match(text):
        if not number_mapping:
            return ParsedCommand(error="当前没有推荐候选人")
        return ParsedCommand(
            candidate_ids=list(number_mapping.values()),
            is_send_all=True,
        )

    # 匹配"发X"格式
    m = _PATTERN_SEND.match(text)
    if not m:
        return ParsedCommand(error=f"无法识别的指令：{text}")

    body = m.group(1).strip()

    # "发"后面跟"全发/全部"
    if _PATTERN_ALL.match(body):
        if not number_mapping:
            return ParsedCommand(error="当前没有推荐候选人")
        return ParsedCommand(
            candidate_ids=list(number_mapping.values()),
            is_send_all=True,
        )

    # 拆分编号
    parts = _SEPARATOR.split(body)
    numbers: list[int] = []
    invalid_parts: list[str] = []

    for part in parts:
        part = part.strip()
        if not part:
            continue
        try:
            num = int(part)
            numbers.append(num)
        except ValueError:
            invalid_parts.append(part)

    if invalid_parts:
        return ParsedCommand(
            error=f"包含无法识别的内容：{'、'.join(invalid_parts)}"
        )

    if not numbers:
        return ParsedCommand(error="未找到有效的候选人编号")

    # 校验编号范围
    out_of_range: list[int] = []
    candidate_ids: list[int] = []

    for num in numbers:
        if num in number_mapping:
            cid = number_mapping[num]
            if cid not in candidate_ids:
                candidate_ids.append(cid)
        else:
            out_of_range.append(num)

    if out_of_range:
        valid_range = sorted(number_mapping.keys())
        range_hint = f"有效编号：{valid_range}" if valid_range else "当前没有推荐候选人"
        return ParsedCommand(
            error=f"编号 {out_of_range} 超出范围，{range_hint}"
        )

    return ParsedCommand(candidate_ids=candidate_ids)


def is_greeting_command(text: str) -> bool:
    """快速判断文本是否为打招呼指令（用于 dispatcher 路��）."""
    text = text.strip()
    if not text:
        return False
    if _PATTERN_ALL.match(text):
        return True
    return bool(_PATTERN_SEND.match(text))
