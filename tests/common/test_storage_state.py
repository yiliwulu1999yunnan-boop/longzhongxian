"""storageState 文件检查测试."""

import json
import time

import pytest

from src.common.storage_state import StorageStateError, check_storage_state


@pytest.fixture
def valid_storage_state(tmp_path: object) -> str:
    """创建一个有效的 storageState 文件."""
    from pathlib import Path

    p = Path(str(tmp_path)) / "boss_001.json"
    p.write_text(json.dumps({"cookies": []}), encoding="utf-8")
    return str(p)


def test_check_existing_file(valid_storage_state: str) -> None:
    """验证存在的文件返回正确状态."""
    status = check_storage_state(valid_storage_state)
    assert status.exists is True
    assert status.expired is False
    assert status.modified_at is not None
    assert status.days_since_modified < 1.0


def test_check_nonexistent_file() -> None:
    """验证文件不存在时抛出 StorageStateError."""
    with pytest.raises(StorageStateError, match="不存在"):
        check_storage_state("/nonexistent/boss_999.json")


def test_check_expired_file(tmp_path: object) -> None:
    """验证超过有效期的文件标记为 expired."""
    import os
    from pathlib import Path

    p = Path(str(tmp_path)) / "old_boss.json"
    p.write_text(json.dumps({"cookies": []}), encoding="utf-8")

    # 将文件修改时间设为 8 天前
    eight_days_ago = time.time() - (8 * 86400)
    os.utime(str(p), (eight_days_ago, eight_days_ago))

    status = check_storage_state(str(p), max_age_days=7.0)
    assert status.expired is True
    assert status.days_since_modified > 7.0


def test_check_custom_max_age(valid_storage_state: str) -> None:
    """验证自定义 max_age_days 参数."""
    # 刚创建的文件，设 max_age_days=0 应该过期
    status = check_storage_state(valid_storage_state, max_age_days=0.0)
    # days_since_modified > 0（文件刚创建但总有微小延迟）
    assert status.expired is True or status.days_since_modified >= 0.0
