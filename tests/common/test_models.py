"""ORM 模型测试 — 用 SQLite 内存库验证全部表结构."""

import pytest
from sqlalchemy import inspect, text

from src.common.config import Settings
from src.common.db import get_engine, get_session_factory
from src.common.models import Base


@pytest.mark.asyncio
async def test_all_tables_created() -> None:
    """验证所有模型能正常创建表结构."""
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:", _env_file=None)
    engine = get_engine(settings)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    expected_tables = {
        "candidates",
        "scoring_snapshots",
        "store_accounts",
        "operation_logs",
        "boss_jobs",
    }

    async with engine.connect() as conn:
        table_names = await conn.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )

    assert expected_tables == table_names

    await engine.dispose()


@pytest.mark.asyncio
async def test_candidates_unique_constraint() -> None:
    """验证 candidates 表的 encrypt_geek_id 唯一约束."""
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:", _env_file=None)
    engine = get_engine(settings)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = get_session_factory(engine)

    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO candidates (encrypt_geek_id, boss_account_id) "
                "VALUES ('geek_001', 'boss_001')"
            )
        )
        await session.commit()

        # 插入重复的 encrypt_geek_id 应失败
        with pytest.raises(Exception):
            await session.execute(
                text(
                    "INSERT INTO candidates (encrypt_geek_id, boss_account_id) "
                    "VALUES ('geek_001', 'boss_002')"
                )
            )
            await session.commit()

    await engine.dispose()


@pytest.mark.asyncio
async def test_scoring_snapshots_fk() -> None:
    """验证 scoring_snapshots 的候选人外键能正常插入."""
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:", _env_file=None)
    engine = get_engine(settings)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = get_session_factory(engine)

    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO candidates (id, encrypt_geek_id) "
                "VALUES (1, 'geek_001')"
            )
        )
        await session.execute(
            text(
                "INSERT INTO scoring_snapshots (candidate_id, final_verdict) "
                "VALUES (1, '推荐沟通')"
            )
        )
        await session.commit()

        result = await session.execute(
            text("SELECT final_verdict FROM scoring_snapshots WHERE candidate_id = 1")
        )
        assert result.scalar() == "推荐沟通"

    await engine.dispose()
