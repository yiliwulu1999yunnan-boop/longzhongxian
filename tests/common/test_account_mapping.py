"""账号映射测试 — YAML 加载 + userid 查询."""

import pytest

from src.common.account_mapping import (
    AccountNotFoundError,
    get_account_by_wechat_userid,
    load_store_accounts,
)


@pytest.fixture
def yaml_path(tmp_path: object) -> str:
    """创建测试用 YAML 配置文件."""
    from pathlib import Path

    p = Path(str(tmp_path)) / "store_accounts.yaml"
    p.write_text(
        """
stores:
  - wechat_userid: "user_001"
    store_id: "store_001"
    store_name: "昆明广场店"
    boss_account_id: "boss_001"
    storage_state_path: "./storage_states/boss_001.json"
    job_type: "面点师"
  - wechat_userid: "user_002"
    store_id: "store_002"
    store_name: "大理古城店"
    boss_account_id: "boss_002"
    storage_state_path: "./storage_states/boss_002.json"
    job_type: "收银员"
""",
        encoding="utf-8",
    )
    return str(p)


def test_load_store_accounts(yaml_path: str) -> None:
    """验证从 YAML 加载门店列表."""
    accounts = load_store_accounts(yaml_path)
    assert len(accounts) == 2
    assert accounts[0]["wechat_userid"] == "user_001"
    assert accounts[1]["store_name"] == "大理古城店"


def test_get_account_by_userid(yaml_path: str) -> None:
    """验证给定 userid 能查到对应的 storageState 路径."""
    info = get_account_by_wechat_userid("user_001", yaml_path)
    assert info.store_id == "store_001"
    assert info.boss_account_id == "boss_001"
    assert info.storage_state_path == "./storage_states/boss_001.json"
    assert info.job_type == "面点师"


def test_get_account_by_userid_second(yaml_path: str) -> None:
    """验证第二个门店也能查到."""
    info = get_account_by_wechat_userid("user_002", yaml_path)
    assert info.store_id == "store_002"
    assert info.boss_account_id == "boss_002"


def test_account_not_found(yaml_path: str) -> None:
    """验证未找到 userid 时抛出 AccountNotFoundError."""
    with pytest.raises(AccountNotFoundError, match="user_999"):
        get_account_by_wechat_userid("user_999", yaml_path)


def test_yaml_file_not_found() -> None:
    """验证 YAML 文件不存在时抛出 FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_store_accounts("/nonexistent/path.yaml")
