"""数据库连接测试 — 用 SQLite 内存库验证 engine + session."""

import pytest
from sqlalchemy import text

from src.common.config import Settings
from src.common.db import get_engine, get_session_factory


@pytest.mark.asyncio
async def test_engine_and_session_lifecycle() -> None:
    """验证 engine 创建、session 执行查询、正常关闭."""
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:", _env_file=None)
    engine = get_engine(settings)
    session_factory = get_session_factory(engine)

    async with session_factory() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    await engine.dispose()
