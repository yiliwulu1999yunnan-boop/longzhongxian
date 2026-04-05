"""BrowserManager 单元测试 — 全部 mock Playwright."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.c1_scraper.browser import BOSS_RECOMMEND_URL, BrowserManager, _normalize_storage_state
from src.common.storage_state import StorageStateError


@pytest.fixture()
def storage_state_file(tmp_path: Path) -> str:
    """创建一个有效的 mock storageState 文件."""
    p = tmp_path / "boss_001.json"
    p.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")
    return str(p)


@pytest.fixture()
def second_storage_state_file(tmp_path: Path) -> str:
    """创建第二个 storageState 文件，用于隔离测试."""
    p = tmp_path / "boss_002.json"
    p.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")
    return str(p)


def _mock_playwright() -> AsyncMock:
    """构造 mock playwright 对象链."""
    mock_pw = AsyncMock()
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()

    mock_pw.chromium.launch.return_value = mock_browser
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page

    return mock_pw


@pytest.mark.asyncio()
async def test_create_context_with_storage_state(storage_state_file: str) -> None:
    """验证 BrowserManager 用 storageState 创建 context."""
    mock_pw = _mock_playwright()

    with patch("src.c1_scraper.browser.async_playwright") as mock_ap:
        mock_ap.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserManager(storage_state_file) as mgr:
            mock_pw.chromium.launch.assert_called_once_with(headless=True)
            call_kwargs = mock_pw.chromium.launch.return_value.new_context.call_args
            # storage_state 现在是 dict（经过 normalize）
            assert isinstance(call_kwargs.kwargs["storage_state"], dict)
            assert mgr.page is not None
            assert mgr.context is not None


@pytest.mark.asyncio()
async def test_multiple_contexts_isolated(
    storage_state_file: str, second_storage_state_file: str
) -> None:
    """验证多个 BrowserManager 实例使用不同 storageState，互相隔离."""
    mock_pw_1 = _mock_playwright()
    mock_pw_2 = _mock_playwright()
    pw_iter = iter([mock_pw_1, mock_pw_2])

    with patch("src.c1_scraper.browser.async_playwright") as mock_ap:
        mock_ap.return_value.start = AsyncMock(side_effect=lambda: next(pw_iter))

        async with BrowserManager(storage_state_file):
            ctx1_call = mock_pw_1.chromium.launch.return_value.new_context.call_args
            state1 = ctx1_call.kwargs["storage_state"]

        async with BrowserManager(second_storage_state_file):
            ctx2_call = mock_pw_2.chromium.launch.return_value.new_context.call_args
            state2 = ctx2_call.kwargs["storage_state"]

    # 两个 context 各自收到了独立的 storage_state dict
    assert isinstance(state1, dict)
    assert isinstance(state2, dict)
    assert storage_state_file != second_storage_state_file


def test_nonexistent_storage_state_raises() -> None:
    """验证 storageState 文件不存在时抛出 StorageStateError."""
    with pytest.raises(StorageStateError, match="不存在"):
        BrowserManager("/nonexistent/path/boss_999.json")


@pytest.mark.asyncio()
async def test_navigate_to_recommend(storage_state_file: str) -> None:
    """验证 navigate_to_recommend 导航到正确 URL."""
    mock_pw = _mock_playwright()

    with patch("src.c1_scraper.browser.async_playwright") as mock_ap:
        mock_ap.return_value.start = AsyncMock(return_value=mock_pw)

        async with BrowserManager(storage_state_file) as mgr:
            await mgr.navigate_to_recommend()
            mock_page = mock_pw.chromium.launch.return_value.new_context.return_value.new_page.return_value
            mock_page.goto.assert_called_once_with(
                BOSS_RECOMMEND_URL, wait_until="domcontentloaded"
            )


def test_normalize_storage_state_fixes_same_site(tmp_path: Path) -> None:
    """验证 _normalize_storage_state 修正 sameSite 大小写."""
    p = tmp_path / "test.json"
    p.write_text(
        json.dumps({
            "cookies": [
                {"name": "a", "value": "1", "sameSite": "lax"},
                {"name": "b", "value": "2", "sameSite": "strict"},
                {"name": "c", "value": "3", "sameSite": "none"},
                {"name": "d", "value": "4", "sameSite": "INVALID"},
                {"name": "e", "value": "5"},
            ],
            "origins": [],
        }),
        encoding="utf-8",
    )
    result = _normalize_storage_state(str(p))
    cookies = result["cookies"]
    assert cookies[0]["sameSite"] == "Lax"
    assert cookies[1]["sameSite"] == "Strict"
    assert cookies[2]["sameSite"] == "None"
    assert cookies[3]["sameSite"] == "Lax"  # invalid → fallback
    assert cookies[4]["sameSite"] == "Lax"  # missing → fallback
