"""筛选报告推送服务单元测试 — 全部 mock，不依赖外部服务."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.c2_scorer.score_merger import MergedVerdict
from src.c3_push.channel import PushChannel
from src.c3_push.report_builder import ReportResult, ScoredCandidate, build_report
from src.c3_push.report_sender import ReportSendError, send_report
from src.common.account_mapping import AccountNotFoundError


def _make_report() -> ReportResult:
    """创建测试用报告."""
    candidates = [
        ScoredCandidate(
            candidate_id=1,
            name="张三",
            merged=MergedVerdict(
                final_verdict="推荐沟通",
                reason="LLM 总分 85",
                highlights=["[LLM] 3年餐饮经验"],
            ),
        ),
    ]
    return build_report(candidates, job_name="服务员")


@pytest.fixture
def yaml_path(tmp_path: object) -> str:
    """创建测试用账号映射 YAML."""
    from pathlib import Path

    p = Path(str(tmp_path)) / "store_accounts.yaml"
    p.write_text(
        """
stores:
  - wechat_userid: "test_user_001"
    store_id: "store_001"
    store_name: "测试门店"
    boss_account_id: "boss_001"
    storage_state_path: "./storage_states/boss_001.json"
    job_type: "服务员"
""",
        encoding="utf-8",
    )
    return str(p)


@pytest.fixture
def mock_channel() -> AsyncMock:
    """创建 mock 推送通道."""
    channel = AsyncMock(spec=PushChannel)
    return channel


class TestSendReportSuccess:
    """正确调用企业微信 API 发送消息."""

    @pytest.mark.asyncio
    async def test_send_markdown_called(
        self, mock_channel: AsyncMock, yaml_path: str
    ) -> None:
        report = _make_report()
        account = await send_report(
            mock_channel, report, "boss_001", yaml_path=yaml_path
        )

        mock_channel.send_markdown.assert_called_once_with(
            "test_user_001", report.markdown
        )
        assert account.wechat_userid == "test_user_001"
        assert account.boss_account_id == "boss_001"

    @pytest.mark.asyncio
    async def test_returns_account_info(
        self, mock_channel: AsyncMock, yaml_path: str
    ) -> None:
        report = _make_report()
        account = await send_report(
            mock_channel, report, "boss_001", yaml_path=yaml_path
        )
        assert account.store_name == "测试门店"
        assert account.store_id == "store_001"


class TestSendReportRetry:
    """发送失败时重试逻辑正确."""

    @pytest.mark.asyncio
    async def test_retry_then_success(
        self, mock_channel: AsyncMock, yaml_path: str
    ) -> None:
        """第一次失败，第二次成功."""
        mock_channel.send_markdown.side_effect = [
            Exception("网络超时"),
            None,  # 第二次成功
        ]
        report = _make_report()
        account = await send_report(
            mock_channel, report, "boss_001", yaml_path=yaml_path, max_retries=2
        )
        assert mock_channel.send_markdown.call_count == 2
        assert account.wechat_userid == "test_user_001"

    @pytest.mark.asyncio
    async def test_retry_exhausted(
        self, mock_channel: AsyncMock, yaml_path: str
    ) -> None:
        """重试耗尽后抛出 ReportSendError."""
        mock_channel.send_markdown.side_effect = Exception("持续失败")
        report = _make_report()

        with pytest.raises(ReportSendError, match="已重试 1 次"):
            await send_report(
                mock_channel, report, "boss_001",
                yaml_path=yaml_path, max_retries=1,
            )
        # 1 次初始 + 1 次重试 = 2 次调用
        assert mock_channel.send_markdown.call_count == 2

    @pytest.mark.asyncio
    async def test_zero_retries(
        self, mock_channel: AsyncMock, yaml_path: str
    ) -> None:
        """max_retries=0 时只尝试一次."""
        mock_channel.send_markdown.side_effect = Exception("失败")
        report = _make_report()

        with pytest.raises(ReportSendError, match="已重试 0 次"):
            await send_report(
                mock_channel, report, "boss_001",
                yaml_path=yaml_path, max_retries=0,
            )
        assert mock_channel.send_markdown.call_count == 1


class TestSendReportAccountNotFound:
    """找不到店长 userid 时抛出明确异常."""

    @pytest.mark.asyncio
    async def test_unknown_boss_raises(
        self, mock_channel: AsyncMock, yaml_path: str
    ) -> None:
        report = _make_report()
        with pytest.raises(AccountNotFoundError, match="boss_999"):
            await send_report(
                mock_channel, report, "boss_999", yaml_path=yaml_path
            )
        # 未找到账号时不应尝试发送
        mock_channel.send_markdown.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_yaml_raises(self, mock_channel: AsyncMock) -> None:
        report = _make_report()
        with pytest.raises(FileNotFoundError):
            await send_report(
                mock_channel, report, "boss_001",
                yaml_path="/nonexistent/path.yaml",
            )
