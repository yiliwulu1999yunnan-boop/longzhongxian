"""数据库连接 — SQLAlchemy async engine + session 管理."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.common.config import Settings


def get_engine(settings: Settings) -> AsyncEngine:
    """根据配置创建 async engine."""
    return create_async_engine(settings.database_url, echo=False)


def get_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """创建 async session 工厂."""
    return async_sessionmaker(engine, expire_on_commit=False)
