"""候选人入库单元测试 — 使用 SQLite 内存数据库，全部 mock."""

from typing import Any, AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.c1_scraper.candidate_store import store_candidates
from src.c1_scraper.detail_extractor import CandidateDetail
from src.common.models import Base, Candidate


@pytest_asyncio.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """创建 SQLite 内存数据库 + session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


def _make_detail(
    encrypt_geek_id: str = "geek_001",
    geek_name: str = "测试候选人",
    **kwargs: Any,
) -> CandidateDetail:
    """构造测试用 CandidateDetail."""
    return CandidateDetail(
        encrypt_geek_id=encrypt_geek_id,
        geek_name=geek_name,
        detail_url=kwargs.get("detail_url", f"/resume/{encrypt_geek_id}"),
        raw_json=kwargs.get("raw_json", {"encryptGeekId": encrypt_geek_id}),
    )


class TestStoreNewCandidates:
    """测试新候选人入库."""

    @pytest.mark.asyncio()
    async def test_store_single_new_candidate(self, db_session: AsyncSession) -> None:
        """单个新候选人正确入库."""
        details = [_make_detail("geek_001", "张三")]
        new = await store_candidates(db_session, details, boss_account_id="boss_1")

        assert len(new) == 1
        assert new[0].encrypt_geek_id == "geek_001"
        assert new[0].boss_account_id == "boss_1"

    @pytest.mark.asyncio()
    async def test_store_multiple_new_candidates(
        self, db_session: AsyncSession
    ) -> None:
        """多个新候选人全部入库."""
        details = [
            _make_detail("geek_001", "张三"),
            _make_detail("geek_002", "李四"),
            _make_detail("geek_003", "王五"),
        ]
        new = await store_candidates(db_session, details)

        assert len(new) == 3
        ids = {c.encrypt_geek_id for c in new}
        assert ids == {"geek_001", "geek_002", "geek_003"}

    @pytest.mark.asyncio()
    async def test_stores_raw_json_and_detail_url(
        self, db_session: AsyncSession
    ) -> None:
        """验证 raw_json 和 detail_url 正确存储."""
        raw = {"encryptGeekId": "geek_001", "extra": "data"}
        details = [
            _make_detail("geek_001", detail_url="/resume/geek_001", raw_json=raw)
        ]
        new = await store_candidates(db_session, details)

        assert new[0].raw_json == raw
        assert new[0].detail_url == "/resume/geek_001"

    @pytest.mark.asyncio()
    async def test_stores_job_id(self, db_session: AsyncSession) -> None:
        """验证 job_id 正确存储."""
        details = [_make_detail("geek_001")]
        new = await store_candidates(
            db_session, details, boss_account_id="boss_1", job_id="job_123"
        )

        assert new[0].job_id == "job_123"

    @pytest.mark.asyncio()
    async def test_empty_list_returns_empty(self, db_session: AsyncSession) -> None:
        """空列表返回空."""
        new = await store_candidates(db_session, [])
        assert new == []


class TestDeduplication:
    """测试去重逻辑."""

    @pytest.mark.asyncio()
    async def test_duplicate_geek_id_not_stored_twice(
        self, db_session: AsyncSession
    ) -> None:
        """重复 encryptGeekId 不重复入库."""
        details = [_make_detail("geek_001", "张三")]

        # 第一次入库
        new1 = await store_candidates(db_session, details)
        assert len(new1) == 1

        # 第二次入库同一候选人
        new2 = await store_candidates(db_session, details)
        assert len(new2) == 0

        # 数据库中只有 1 条
        result = await db_session.execute(select(Candidate))
        all_rows = result.scalars().all()
        assert len(all_rows) == 1

    @pytest.mark.asyncio()
    async def test_same_batch_dedup(self, db_session: AsyncSession) -> None:
        """同批次内重复 encryptGeekId 只入库一次."""
        details = [
            _make_detail("geek_001", "张三"),
            _make_detail("geek_001", "张三副本"),
        ]
        new = await store_candidates(db_session, details)

        assert len(new) == 1
        assert new[0].encrypt_geek_id == "geek_001"

    @pytest.mark.asyncio()
    async def test_mixed_new_and_existing(self, db_session: AsyncSession) -> None:
        """混合新旧候选人时只返回新增的."""
        # 先入库一个
        await store_candidates(
            db_session, [_make_detail("geek_001", "张三")]
        )

        # 再入库包含已有和新增的
        details = [
            _make_detail("geek_001", "张三"),
            _make_detail("geek_002", "李四"),
        ]
        new = await store_candidates(db_session, details)

        assert len(new) == 1
        assert new[0].encrypt_geek_id == "geek_002"


class TestReturnedCandidates:
    """测试返回的候选人列表供后续打分."""

    @pytest.mark.asyncio()
    async def test_returned_candidates_have_id(
        self, db_session: AsyncSession
    ) -> None:
        """返回的候选人有数据库 ID（flush 后可用）."""
        details = [_make_detail("geek_001")]
        new = await store_candidates(db_session, details)

        assert new[0].id is not None
        assert new[0].id > 0

    @pytest.mark.asyncio()
    async def test_returned_candidates_are_orm_objects(
        self, db_session: AsyncSession
    ) -> None:
        """返回 Candidate ORM 对象，可直接用于后续操作."""
        details = [_make_detail("geek_001"), _make_detail("geek_002")]
        new = await store_candidates(db_session, details)

        assert all(isinstance(c, Candidate) for c in new)
        assert all(c.encrypt_geek_id for c in new)
