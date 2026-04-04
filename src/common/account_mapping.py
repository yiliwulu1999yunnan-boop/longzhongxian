"""账号映射 — 企业微信 userid → 门店 → Boss 账号 → storageState."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class AccountNotFoundError(Exception):
    """未找到对应的门店账号映射."""


@dataclass(frozen=True)
class StoreAccountInfo:
    """门店账号映射信息."""

    wechat_userid: str
    store_id: str
    store_name: str
    boss_account_id: str
    storage_state_path: str
    job_type: str


def load_store_accounts(yaml_path: str | Path) -> list[dict[str, Any]]:
    """从 YAML 配置文件加载门店账号列表."""
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"账号配置文件不存在: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data or "stores" not in data:
        raise ValueError(f"配置文件格式错误，缺少 'stores' 字段: {path}")
    return data["stores"]


def get_account_by_wechat_userid(
    userid: str,
    yaml_path: str | Path = "config/store_accounts.yaml",
) -> StoreAccountInfo:
    """根据企业微信 userid 查找门店账号映射."""
    accounts = load_store_accounts(yaml_path)
    for acc in accounts:
        if acc.get("wechat_userid") == userid:
            return StoreAccountInfo(
                wechat_userid=acc["wechat_userid"],
                store_id=acc["store_id"],
                store_name=acc.get("store_name", ""),
                boss_account_id=acc["boss_account_id"],
                storage_state_path=acc["storage_state_path"],
                job_type=acc.get("job_type", ""),
            )
    raise AccountNotFoundError(f"未找到企业微信 userid={userid} 的账号映射")
