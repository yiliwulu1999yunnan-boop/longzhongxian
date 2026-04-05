"""C1 端到端集成测试 — Playwright mock route 模拟完整链路.

使用 Playwright 真实浏览器 + route 拦截，不访问 Boss 直聘。
数据库使用 SQLite 内存实例。
"""

import json
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from playwright.async_api import Route, async_playwright
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.c1_scraper.candidate_store import store_candidates
from src.c1_scraper.detail_extractor import parse_candidate_detail
from src.c1_scraper.recommend_scraper import parse_recommend_response
from src.common.models import Base, Candidate

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RECOMMEND_HTML = (FIXTURES_DIR / "recommend_page.html").read_text(encoding="utf-8")
WAPI_RESPONSE = json.loads(
    (FIXTURES_DIR / "wapi_recommend.json").read_text(encoding="utf-8")
)


@pytest_asyncio.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """SQLite 内存数据库 session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


class TestC1PipelineNormal:
    """正常流程：抓取 → 解析 → 入库."""

    @pytest.mark.asyncio()
    async def test_full_pipeline_scrape_parse_store(
        self, db_session: AsyncSession
    ) -> None:
        """完整链路：Playwright 拦截 → 解析候选人 → 入库."""
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context()

            # mock route: 页面请求返回 mock HTML
            async def _handle_page(route: Route) -> None:
                await route.fulfill(
                    status=200,
                    content_type="text/html",
                    body=RECOMMEND_HTML,
                )

            # mock route: /wapi/ 请求返回 mock JSON
            async def _handle_wapi(route: Route) -> None:
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(WAPI_RESPONSE),
                )

            await context.route("**/web/chat/recommend**", _handle_page)
            await context.route("**/wapi/**", _handle_wapi)

            page = await context.new_page()

            # 收集拦截到的候选人
            collected = []

            async def _on_response(response):  # type: ignore[no-untyped-def]
                url = response.url
                if "/wapi/" not in url:
                    return
                try:
                    body = await response.json()
                    parsed = parse_recommend_response(body)
                    collected.extend(parsed)
                except Exception:
                    pass

            context.on("response", _on_response)

            # 导航到推荐页
            await page.goto(
                "https://www.zhipin.com/web/chat/recommend",
                wait_until="domcontentloaded",
            )
            # 等待 fetch 请求完成
            await page.wait_for_timeout(2000)

            # 验证拦截到候选人
            assert len(collected) == 3

            # 解析详情
            details = []
            for rc in collected:
                detail = parse_candidate_detail(rc.raw_json)
                assert detail is not None
                details.append(detail)

            assert len(details) == 3
            assert details[0].geek_name == "集成测试候选人A"
            assert details[0].expect_position == "面点师"
            assert len(details[0].work_experiences) == 1
            assert len(details[0].educations) == 1

            # 入库
            new_candidates = await store_candidates(
                db_session, details, boss_account_id="test_boss", job_id="test_job"
            )

            assert len(new_candidates) == 3
            assert all(c.id is not None for c in new_candidates)
            assert {c.encrypt_geek_id for c in new_candidates} == {
                "integ_geek_001",
                "integ_geek_002",
                "integ_geek_003",
            }

            # 验证 DB 持久化
            result = await db_session.execute(select(Candidate))
            rows = result.scalars().all()
            assert len(rows) == 3
            assert all(r.boss_account_id == "test_boss" for r in rows)
            assert all(r.job_id == "test_job" for r in rows)

            await context.close()
            await browser.close()


class TestC1PipelineDedup:
    """去重流程：同一候选人第二次运行不重复入库."""

    @pytest.mark.asyncio()
    async def test_second_run_no_duplicates(
        self, db_session: AsyncSession
    ) -> None:
        """第二次运行同样数据，不产生重复记录."""
        # 直接用 parse + store 模拟两次运行（不需要再启动浏览器）
        details = []
        for item in WAPI_RESPONSE["zpData"]["geekList"]:
            detail = parse_candidate_detail(item)
            assert detail is not None
            details.append(detail)

        # 第一次入库
        new1 = await store_candidates(db_session, details, boss_account_id="boss_1")
        assert len(new1) == 3

        # 第二次入库（模拟第二次抓取同样的候选人）
        new2 = await store_candidates(db_session, details, boss_account_id="boss_1")
        assert len(new2) == 0

        # DB 中仍然只有 3 条
        result = await db_session.execute(select(Candidate))
        assert len(result.scalars().all()) == 3

    @pytest.mark.asyncio()
    async def test_partial_overlap(self, db_session: AsyncSession) -> None:
        """部分重叠：已有候选人跳过，新候选人入库."""
        geek_list = WAPI_RESPONSE["zpData"]["geekList"]

        # 先入库前 2 个
        first_batch = [parse_candidate_detail(g) for g in geek_list[:2]]
        await store_candidates(
            db_session, [d for d in first_batch if d is not None]
        )

        # 再入库全部 3 个
        all_details = [parse_candidate_detail(g) for g in geek_list]
        new = await store_candidates(
            db_session, [d for d in all_details if d is not None]
        )

        # 只新增了第 3 个
        assert len(new) == 1
        assert new[0].encrypt_geek_id == "integ_geek_003"


class TestC1PipelineErrorHandling:
    """异常降级：网络异常、数据缺失时的容错."""

    @pytest.mark.asyncio()
    async def test_empty_wapi_response(self, db_session: AsyncSession) -> None:
        """wapi 返回空列表时，流程正常结束不报错."""
        empty_response: dict = {
            "code": 0,
            "message": "Success",
            "zpData": {"hasMore": False, "geekList": []},
        }
        parsed = parse_recommend_response(empty_response)
        assert parsed == []

        new = await store_candidates(db_session, [])
        assert new == []

    @pytest.mark.asyncio()
    async def test_malformed_candidate_skipped(
        self, db_session: AsyncSession
    ) -> None:
        """畸形候选人数据被跳过，不影响其他候选人."""
        mixed_list = [
            # 正常候选人
            WAPI_RESPONSE["zpData"]["geekList"][0],
            # 缺少 encryptGeekId
            {"geekName": "无ID"},
            # 缺少 geekName
            {"encryptGeekId": "no_name_id"},
        ]

        details = []
        for item in mixed_list:
            detail = parse_candidate_detail(item)
            if detail is not None:
                details.append(detail)

        # 只有 1 个有效
        assert len(details) == 1
        assert details[0].encrypt_geek_id == "integ_geek_001"

        new = await store_candidates(db_session, details)
        assert len(new) == 1

    @pytest.mark.asyncio()
    async def test_network_error_wapi_returns_empty(self) -> None:
        """Playwright route 返回错误状态码时，拦截器不崩溃."""
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context()

            async def _handle_page(route: Route) -> None:
                await route.fulfill(
                    status=200,
                    content_type="text/html",
                    body="<html><body>empty</body></html>",
                )

            async def _handle_wapi_error(route: Route) -> None:
                await route.fulfill(status=500, body="Internal Server Error")

            await context.route("**/web/chat/recommend**", _handle_page)
            await context.route("**/wapi/**", _handle_wapi_error)

            page = await context.new_page()
            collected = []

            async def _on_response(response):  # type: ignore[no-untyped-def]
                if "/wapi/" not in response.url:
                    return
                try:
                    body = await response.json()
                    parsed = parse_recommend_response(body)
                    collected.extend(parsed)
                except Exception:
                    pass  # 错误响应无法解析 JSON，正常跳过

            context.on("response", _on_response)

            await page.goto(
                "https://www.zhipin.com/web/chat/recommend",
                wait_until="domcontentloaded",
            )
            await page.wait_for_timeout(1000)

            # 没有候选人被收集到
            assert len(collected) == 0

            await context.close()
            await browser.close()
