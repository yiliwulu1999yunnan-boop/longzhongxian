"""应用配置 — 基于 pydantic-settings 从 .env.local 加载环境变量."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    # PostgreSQL
    database_url: str = ""

    # 企业微信
    wechat_corp_id: str = ""
    wechat_agent_id: str = ""
    wechat_secret: str = ""
    wechat_token: str = ""
    wechat_encoding_aes_key: str = ""

    # Boss 直聘
    storage_states_dir: str = "./storage_states"
    cdp_endpoint: str = ""  # e.g. "http://localhost:9222"

    # 日志
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例."""
    return Settings()
