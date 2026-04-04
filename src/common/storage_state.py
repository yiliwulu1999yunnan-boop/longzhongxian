"""storageState 文件检查 — 存在性验证 + 过期预警."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class StorageStateError(Exception):
    """storageState 文件异常."""


@dataclass(frozen=True)
class StorageStateStatus:
    """storageState 文件状态."""

    exists: bool
    path: str
    modified_at: datetime | None
    expired: bool
    days_since_modified: float


def check_storage_state(
    path: str | Path,
    max_age_days: float = 7.0,
) -> StorageStateStatus:
    """检查 storageState 文件状态.

    Args:
        path: storageState 文件路径
        max_age_days: 最大有效天数，超过则视为过期

    Returns:
        StorageStateStatus 包含文件状态信息

    Raises:
        StorageStateError: 文件不存在时抛出
    """
    p = Path(path)
    if not p.exists():
        raise StorageStateError(f"storageState 文件不存在: {path}")

    mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    days = (now - mtime).total_seconds() / 86400.0

    return StorageStateStatus(
        exists=True,
        path=str(p),
        modified_at=mtime,
        expired=days > max_age_days,
        days_since_modified=round(days, 2),
    )
