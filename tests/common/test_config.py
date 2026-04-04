"""Settings 配置加载测试."""

import os

from src.common.config import Settings


def test_settings_loads_all_fields_from_env(monkeypatch: object) -> None:
    """验证 Settings 能从环境变量加载 .env.example 中的全部字段."""
    import pytest

    mp = pytest.MonkeyPatch()
    mp.setenv("DEEPSEEK_API_KEY", "sk-test-key")
    mp.setenv("DEEPSEEK_BASE_URL", "https://custom.api")
    mp.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    mp.setenv("WECHAT_CORP_ID", "corp-123")
    mp.setenv("WECHAT_AGENT_ID", "agent-456")
    mp.setenv("WECHAT_SECRET", "secret-789")
    mp.setenv("WECHAT_TOKEN", "token-abc")
    mp.setenv("WECHAT_ENCODING_AES_KEY", "aes-key-def")
    mp.setenv("STORAGE_STATES_DIR", "/tmp/states")
    mp.setenv("LOG_LEVEL", "DEBUG")

    s = Settings()

    assert s.deepseek_api_key == "sk-test-key"
    assert s.deepseek_base_url == "https://custom.api"
    assert s.database_url == "postgresql+asyncpg://u:p@localhost/db"
    assert s.wechat_corp_id == "corp-123"
    assert s.wechat_agent_id == "agent-456"
    assert s.wechat_secret == "secret-789"
    assert s.wechat_token == "token-abc"
    assert s.wechat_encoding_aes_key == "aes-key-def"
    assert s.storage_states_dir == "/tmp/states"
    assert s.log_level == "DEBUG"

    mp.undo()


def test_settings_defaults() -> None:
    """验证未设置环境变量时使用默认值."""
    # 清除可能存在的环境变量
    env_keys = [
        "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DATABASE_URL",
        "WECHAT_CORP_ID", "WECHAT_AGENT_ID", "WECHAT_SECRET",
        "WECHAT_TOKEN", "WECHAT_ENCODING_AES_KEY",
        "STORAGE_STATES_DIR", "LOG_LEVEL",
    ]
    saved = {}
    for key in env_keys:
        if key in os.environ:
            saved[key] = os.environ.pop(key)

    try:
        s = Settings(_env_file=None)
        assert s.deepseek_api_key == ""
        assert s.deepseek_base_url == "https://api.deepseek.com"
        assert s.database_url == ""
        assert s.storage_states_dir == "./storage_states"
        assert s.log_level == "INFO"
    finally:
        os.environ.update(saved)
