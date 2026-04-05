"""筛选报告生成器单元测试."""

from __future__ import annotations

from src.c2_scorer.score_merger import MergedVerdict
from src.c3_push.report_builder import (
    ReportResult,
    ScoredCandidate,
    _mask_name,
    build_report,
)


def _make_candidate(
    candidate_id: int,
    name: str,
    verdict: str,
    *,
    risks: list[str] | None = None,
    highlights: list[str] | None = None,
    work_years: str = "",
    age: str = "",
) -> ScoredCandidate:
    """创建测试用候选人."""
    return ScoredCandidate(
        candidate_id=candidate_id,
        name=name,
        merged=MergedVerdict(
            final_verdict=verdict,
            reason="测试原因",
            risks=risks or [],
            highlights=highlights or [],
        ),
        work_years=work_years,
        age=age,
    )


class TestMaskName:
    def test_normal_name(self) -> None:
        assert _mask_name("张三") == "张*"

    def test_three_char_name(self) -> None:
        assert _mask_name("欧阳锋") == "欧**"

    def test_single_char(self) -> None:
        assert _mask_name("张") == "张"

    def test_empty_name(self) -> None:
        assert _mask_name("") == "匿名"


class TestBuildReportZeroRecommend:
    """0 个推荐候选人时报告仍完整."""

    def test_no_candidates(self) -> None:
        result = build_report([])
        assert isinstance(result, ReportResult)
        assert result.total == 0
        assert result.recommend_count == 0
        assert result.maybe_count == 0
        assert result.reject_count == 0
        assert result.number_mapping == {}
        assert "共筛选 **0** 人" in result.markdown
        assert "本次无推荐沟通候选人" in result.markdown

    def test_only_reject(self) -> None:
        candidates = [
            _make_candidate(1, "李四", "不建议"),
            _make_candidate(2, "王五", "不建议"),
        ]
        result = build_report(candidates)
        assert result.total == 2
        assert result.recommend_count == 0
        assert result.reject_count == 2
        assert result.number_mapping == {}
        assert "本次无推荐沟通候选人" in result.markdown

    def test_only_maybe(self) -> None:
        candidates = [_make_candidate(1, "赵六", "可以看看")]
        result = build_report(candidates)
        assert result.recommend_count == 0
        assert result.maybe_count == 1
        assert "本次无推荐沟通候选人" in result.markdown


class TestBuildReportMultipleRecommend:
    """多个推荐候选人时摘要格式正确、编号连续."""

    def test_multiple_recommend_numbering(self) -> None:
        candidates = [
            _make_candidate(
                10, "张三", "推荐沟通",
                highlights=["[LLM] 3年餐饮经验"],
                work_years="3年",
                age="25岁",
            ),
            _make_candidate(
                20, "李四", "推荐沟通",
                highlights=["[LLM] 有管理经验"],
                risks=["⚠️ 频繁跳槽"],
                work_years="5年",
            ),
            _make_candidate(30, "王五", "可以看看"),
            _make_candidate(40, "赵六", "不建议"),
        ]
        result = build_report(candidates, job_name="服务员")
        md = result.markdown

        # 统计正确
        assert result.total == 4
        assert result.recommend_count == 2
        assert result.maybe_count == 1
        assert result.reject_count == 1

        # 编号连续且映射正确
        assert result.number_mapping == {1: 10, 2: 20}

        # 标题包含岗位名
        assert "服务员" in md

        # 编号出现在报告中
        assert "**1. 张*" in md
        assert "**2. 李*" in md

        # 亮点和风险出现
        assert "3年餐饮经验" in md
        assert "频繁跳槽" in md

        # 工作年限出现
        assert "3年" in md
        assert "5年" in md

        # 可以看看和不建议只显示人数
        assert "可以看看（1 人）" in md
        assert "不建议（1 人）" in md

        # 操作提示
        assert "发1、3" in md

    def test_single_recommend(self) -> None:
        candidates = [
            _make_candidate(
                100, "孙七", "推荐沟通",
                highlights=["[LLM] 经验丰富"],
            ),
        ]
        result = build_report(candidates)
        assert result.recommend_count == 1
        assert result.number_mapping == {1: 100}
        assert "**1. 孙*" in result.markdown


class TestMarkdownFormat:
    """Markdown 输出符合企业微信格式规范."""

    def test_uses_heading_syntax(self) -> None:
        result = build_report([], job_name="店长")
        md = result.markdown
        assert md.startswith("## AI 筛选报告 - 店长")

    def test_no_job_name(self) -> None:
        result = build_report([])
        assert "## AI 筛选报告\n" in result.markdown

    def test_bold_markers(self) -> None:
        candidates = [_make_candidate(1, "张三", "推荐沟通")]
        result = build_report(candidates)
        # 企业微信 Markdown 使用 ** 加粗
        assert "**" in result.markdown

    def test_truncation_on_long_content(self) -> None:
        """候选人数量多时报告会截断."""
        candidates = [
            _make_candidate(
                i, f"候选人{i}", "推荐沟通",
                highlights=[f"亮点描述较长内容{i}" * 5],
                risks=[f"风险描述较长内容{i}" * 5],
                work_years="10年",
                age="30岁",
            )
            for i in range(50)
        ]
        result = build_report(candidates)
        md_bytes = result.markdown.encode("utf-8")
        # 不超过限制
        assert len(md_bytes) <= 2048
        assert "已截断" in result.markdown
