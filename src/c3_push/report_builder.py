"""筛选报告内容生成 — 将评分结果格式化为企业微信 Markdown 报告."""

from __future__ import annotations

from dataclasses import dataclass

from src.c2_scorer.score_merger import MergedVerdict

# 企业微信 Markdown 消息内容限制（官方限制约 2048 字节，留安全余量）
_MAX_CONTENT_LENGTH = 1800
_VERDICT_RECOMMEND = "推荐沟通"
_VERDICT_MAYBE = "可以看看"
_VERDICT_REJECT = "不建议"


@dataclass
class ScoredCandidate:
    """报告生成器的输入：一个候选人的评分结果 + 基本信息."""

    candidate_id: int
    name: str  # 脱敏姓名（如"张*"）
    merged: MergedVerdict
    work_years: str = ""
    age: str = ""


@dataclass
class ReportResult:
    """报告生成器的输出."""

    markdown: str
    total: int
    recommend_count: int
    maybe_count: int
    reject_count: int
    # 编号 → candidate_id 映射，供 C4 指令引用
    number_mapping: dict[int, int]


def _mask_name(name: str) -> str:
    """姓名脱敏：保留姓 + 先生/女士，无法判断性别时用 *."""
    if not name:
        return "匿名"
    return name[0] + "先生"


def build_report(
    candidates: list[ScoredCandidate],
    job_name: str = "",
) -> ReportResult:
    """将评分结果列表格式化为企业微信 Markdown 筛选报告.

    Args:
        candidates: 本次筛选的全部候选人评分结果.
        job_name: 岗位名称（可选，用于报告标题）.

    Returns:
        ReportResult 包含格式化的 Markdown 和统计信息.
    """
    recommend: list[ScoredCandidate] = []
    maybe: list[ScoredCandidate] = []
    reject: list[ScoredCandidate] = []

    for c in candidates:
        verdict = c.merged.final_verdict
        if verdict == _VERDICT_RECOMMEND:
            recommend.append(c)
        elif verdict == _VERDICT_MAYBE:
            maybe.append(c)
        else:
            reject.append(c)

    total = len(candidates)
    number_mapping: dict[int, int] = {}

    # 标题（# 一级标题，最大字号）
    title = "AI 筛选报告"
    if job_name:
        title = f"AI 筛选报告 · {job_name}"

    lines: list[str] = [f"#### {title}"]

    # 总览（灰色辅助文字）
    lines.append(
        f'<font color="comment">'
        f"共 {total} 人：推荐 {len(recommend)} / 观望 {len(maybe)} / 不建议 {len(reject)}"
        f"</font>"
    )

    # 推荐候选人摘要（带编号）
    if recommend:
        lines.append("")
        lines.append(f'**推荐沟通（{len(recommend)} 人）**')
        for idx, c in enumerate(recommend, start=1):
            number_mapping[idx] = c.candidate_id
            entry = _format_candidate_entry(idx, c)
            lines.append(entry)
    else:
        lines.append("")
        lines.append("本次无推荐沟通候选人")

    # 可以看看 / 不建议：有数据才显示
    if maybe:
        lines.append("")
        lines.append(
            f'<font color="comment">观望 {len(maybe)} 人，暂不展开</font>'
        )
    if reject:
        lines.append(
            f'<font color="comment">不建议 {len(reject)} 人</font>'
        )

    # 操作提示
    if recommend:
        lines.append("")
        lines.append('> 回复编号发起沟通，如「发1、3」或「全发」')

    markdown = _truncate_markdown("\n".join(lines))

    return ReportResult(
        markdown=markdown,
        total=total,
        recommend_count=len(recommend),
        maybe_count=len(maybe),
        reject_count=len(reject),
        number_mapping=number_mapping,
    )


def _format_candidate_entry(idx: int, c: ScoredCandidate) -> str:
    """格式化单个推荐候选人条目."""
    masked = _mask_name(c.name)
    merged = c.merged

    # 候选人名（加粗）+ 基本信息（灰色辅助）
    meta_parts: list[str] = []
    if c.work_years:
        meta_parts.append(c.work_years)
    if c.age:
        meta_parts.append(c.age)
    meta = f' <font color="comment">{" · ".join(meta_parts)}</font>' if meta_parts else ""
    header = f"**{idx}. {masked}**{meta}"

    parts = [header]

    # 亮点（绿色）
    if merged.highlights:
        hl_text = "；".join(merged.highlights[:3])
        parts.append(f'<font color="info">{hl_text}</font>')

    # 风险（橙色警告）
    if merged.risks:
        risk_text = "；".join(merged.risks[:2])
        parts.append(f'<font color="warning">⚠️ {risk_text}</font>')

    return "\n".join(parts)


def _truncate_markdown(content: str) -> str:
    """如果内容超过企业微信限制，截断并添加省略提示."""
    if len(content.encode("utf-8")) <= _MAX_CONTENT_LENGTH:
        return content

    # 按行截断，保证不超限
    lines = content.split("\n")
    result_lines: list[str] = []
    current_size = 0
    suffix = "\n\n> ⚠️ 报告内容过长，已截断"
    suffix_size = len(suffix.encode("utf-8"))

    for line in lines:
        line_size = len(line.encode("utf-8")) + 1  # +1 for \n
        if current_size + line_size + suffix_size > _MAX_CONTENT_LENGTH:
            break
        result_lines.append(line)
        current_size += line_size

    result_lines.append("")
    result_lines.append("> ⚠️ 报告内容过长，已截断")
    return "\n".join(result_lines)
