"""筛选链路编排单元测试 — mock 各子模块，验证步骤按序调用和错误处理."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.c2_scorer.hard_rules import HardRuleVerdict
from src.c2_scorer.pipeline import C2Result
from src.c2_scorer.score_merger import MergedVerdict
from src.c3_push.channel import PushChannel
from src.common.models import Candidate
from src.common.screening_pipeline import run_screening


@pytest.fixture
def yaml_path(tmp_path: Path) -> str:
    """创建测试用账号映射 YAML."""
    p = tmp_path / "store_accounts.yaml"
    p.write_text(
        """
stores:
  - wechat_userid: "user_001"
    store_id: "store_001"
    store_name: "测试门店"
    boss_account_id: "boss_001"
    storage_state_path: "./storage_states/boss_001.json"
    job_type: "服务员"
""",
        encoding="utf-8",
    )
    return str(p)


def _make_candidate(cid: int, name: str = "张三") -> MagicMock:
    """创建测试用 Candidate mock 对象."""
    c = MagicMock(spec=Candidate)
    c.id = cid
    c.encrypt_geek_id = f"geek_{cid}"
    c.raw_json = {
        "encryptGeekId": f"geek_{cid}",
        "geekCard": {
            "geekName": name,
            "ageDesc": "25岁",
            "geekWorkYear": "3年",
            "geekDegree": "高中",
        },
    }
    c.detail_url = ""
    c.boss_account_id = "boss_001"
    c.job_id = ""
    return c


def _make_c2_result(verdict: str = "推荐沟通") -> C2Result:
    """创建测试用 C2Result."""
    merged = MergedVerdict(
        final_verdict=verdict,
        reason="测试",
        highlights=["亮点1"],
        risks=["风险1"],
    )
    return C2Result(
        hard_verdict=HardRuleVerdict(passed=True, is_reject=False, results=[], whitelist_hits=[], blacklist_hits=[]),
        llm_result=None,
        merged=merged,
        snapshot=None,
    )


def _mock_profile() -> MagicMock:
    """创建 mock 岗位画像."""
    profile = MagicMock()
    profile.position_name = "服务员"
    profile.llm_evaluation.passing_score = 60
    profile.config_version = "test:v1"
    return profile


class TestScreeningPipelineSteps:
    """验证各步骤按序调用."""

    @pytest.mark.asyncio
    @patch("src.common.screening_pipeline.run_c1_pipeline")
    @patch("src.common.screening_pipeline.run_c2_pipeline")
    @patch("src.common.screening_pipeline.send_report")
    async def test_full_pipeline_steps(
        self,
        mock_send: AsyncMock,
        mock_c2: AsyncMock,
        mock_c1: AsyncMock,
        yaml_path: str,
    ) -> None:
        """C1 → C2 → C3 按序调用."""
        candidates = [_make_candidate(1, "张三"), _make_candidate(2, "李四")]
        mock_c1.return_value = candidates
        mock_c2.return_value = _make_c2_result("推荐沟通")

        mock_browser = AsyncMock()
        mock_browser.storage_state_expiry_warning = False
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_channel = AsyncMock(spec=PushChannel)
        mock_scorer = AsyncMock()
        profile = _mock_profile()

        result = await run_screening(
            mock_browser, mock_session, mock_channel, mock_scorer, profile,
            boss_account_id="boss_001", yaml_path=yaml_path,
        )

        # C1 被调用
        mock_c1.assert_called_once()
        # C2 对每个候选人调用一次
        assert mock_c2.call_count == 2
        # C3 发送报告
        mock_send.assert_called_once()

        assert result.candidates_scraped == 2
        assert result.candidates_scored == 2
        assert result.report_sent is True
        assert result.error is None

    @pytest.mark.asyncio
    @patch("src.common.screening_pipeline.run_c1_pipeline")
    @patch("src.common.screening_pipeline.send_report")
    async def test_no_new_candidates(
        self,
        mock_send: AsyncMock,
        mock_c1: AsyncMock,
        yaml_path: str,
    ) -> None:
        """C1 返回空列表时，通知店长并返回."""
        mock_c1.return_value = []

        mock_browser = AsyncMock()
        mock_browser.storage_state_expiry_warning = False
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_channel = AsyncMock(spec=PushChannel)
        mock_scorer = AsyncMock()
        profile = _mock_profile()

        result = await run_screening(
            mock_browser, mock_session, mock_channel, mock_scorer, profile,
            boss_account_id="boss_001", yaml_path=yaml_path,
        )

        assert result.candidates_scraped == 0
        assert result.candidates_scored == 0
        # 通知店长"无新候选人"
        mock_channel.send_text.assert_called_once()
        # 不调用 send_report
        mock_send.assert_not_called()


class TestScreeningPipelineErrors:
    """某步骤失败时错误通知逻辑正确."""

    @pytest.mark.asyncio
    @patch("src.common.screening_pipeline.run_c1_pipeline")
    async def test_c1_failure_notifies(
        self,
        mock_c1: AsyncMock,
        yaml_path: str,
    ) -> None:
        """C1 失败时通知店长并记录日志."""
        mock_c1.side_effect = RuntimeError("Playwright 连接失败")

        mock_browser = AsyncMock()
        mock_browser.storage_state_expiry_warning = False
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_channel = AsyncMock(spec=PushChannel)
        mock_scorer = AsyncMock()
        profile = _mock_profile()

        result = await run_screening(
            mock_browser, mock_session, mock_channel, mock_scorer, profile,
            boss_account_id="boss_001", yaml_path=yaml_path,
        )

        assert result.error is not None
        assert "C1 失败" in result.error
        assert result.report_sent is False
        # 通知店长
        mock_channel.send_text.assert_called_once()
        call_args = mock_channel.send_text.call_args
        assert "简历获取失败" in call_args[0][1]

    @pytest.mark.asyncio
    @patch("src.common.screening_pipeline.run_c1_pipeline")
    @patch("src.common.screening_pipeline.run_c2_pipeline")
    @patch("src.common.screening_pipeline.send_report")
    async def test_c2_partial_failure(
        self,
        mock_send: AsyncMock,
        mock_c2: AsyncMock,
        mock_c1: AsyncMock,
        yaml_path: str,
    ) -> None:
        """C2 对某个候选人失败时跳过该候选人，继续其余."""
        candidates = [_make_candidate(1, "张三"), _make_candidate(2, "李四")]
        mock_c1.return_value = candidates
        # 第一个成功，第二个失败
        mock_c2.side_effect = [
            _make_c2_result("推荐沟通"),
            RuntimeError("LLM 超时"),
        ]

        mock_browser = AsyncMock()
        mock_browser.storage_state_expiry_warning = False
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_channel = AsyncMock(spec=PushChannel)
        mock_scorer = AsyncMock()
        profile = _mock_profile()

        result = await run_screening(
            mock_browser, mock_session, mock_channel, mock_scorer, profile,
            boss_account_id="boss_001", yaml_path=yaml_path,
        )

        assert result.candidates_scraped == 2
        assert result.candidates_scored == 1  # 只有第一个成功
        assert result.report_sent is True

    @pytest.mark.asyncio
    @patch("src.common.screening_pipeline.run_c1_pipeline")
    @patch("src.common.screening_pipeline.run_c2_pipeline")
    @patch("src.common.screening_pipeline.send_report")
    async def test_c3_send_failure(
        self,
        mock_send: AsyncMock,
        mock_c2: AsyncMock,
        mock_c1: AsyncMock,
        yaml_path: str,
    ) -> None:
        """C3 推送失败时 report_sent=False."""
        mock_c1.return_value = [_make_candidate(1)]
        mock_c2.return_value = _make_c2_result()
        mock_send.side_effect = RuntimeError("企业微信 API 异常")

        mock_browser = AsyncMock()
        mock_browser.storage_state_expiry_warning = False
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_channel = AsyncMock(spec=PushChannel)
        mock_scorer = AsyncMock()
        profile = _mock_profile()

        result = await run_screening(
            mock_browser, mock_session, mock_channel, mock_scorer, profile,
            boss_account_id="boss_001", yaml_path=yaml_path,
        )

        assert result.candidates_scored == 1
        assert result.report_sent is False
