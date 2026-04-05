"""企业微信应用消息客户端 — access_token 管理 + 消息发送."""

import time

import httpx

from src.common.config import get_settings

_BASE_URL = "https://qyapi.weixin.qq.com/cgi-bin"


class WechatClientError(Exception):
    """企业微信 API 调用失败."""


class WechatClient:
    """企业微信应用消息客户端.

    负责 access_token 的获取与缓存，以及文本/Markdown 消息发送。
    """

    def __init__(
        self,
        corp_id: str | None = None,
        corp_secret: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        settings = get_settings()
        self._corp_id = corp_id or settings.wechat_corp_id
        self._corp_secret = corp_secret or settings.wechat_secret
        self._agent_id = agent_id or settings.wechat_agent_id
        self._access_token: str = ""
        self._token_expires_at: float = 0.0

    # ───────── access_token ─────────

    async def _fetch_access_token(self) -> tuple[str, int]:
        """从企业微信 API 获取 access_token，返回 (token, expires_in)."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_BASE_URL}/gettoken",
                params={"corpid": self._corp_id, "corpsecret": self._corp_secret},
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("errcode", 0) != 0:
            raise WechatClientError(
                f"获取 access_token 失败: {data.get('errmsg', 'unknown')}"
            )
        return data["access_token"], data["expires_in"]

    async def get_access_token(self) -> str:
        """获取 access_token，自动缓存并在过期前刷新."""
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        token, expires_in = await self._fetch_access_token()
        self._access_token = token
        # 提前 5 分钟刷新，避免边界问题
        self._token_expires_at = time.time() + expires_in - 300
        return self._access_token

    # ───────── 发送消息 ─────────

    async def _send_message(self, payload: dict) -> dict:
        """发送消息到企业微信 API."""
        token = await self.get_access_token()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{_BASE_URL}/message/send",
                params={"access_token": token},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("errcode", 0) != 0:
            raise WechatClientError(
                f"发送消息失败: {data.get('errmsg', 'unknown')}"
            )
        return data

    async def send_text(self, user_id: str, content: str) -> dict:
        """发送文本消息给指定用户."""
        return await self._send_message({
            "touser": user_id,
            "msgtype": "text",
            "agentid": self._agent_id,
            "text": {"content": content},
        })

    async def send_markdown(self, user_id: str, content: str) -> dict:
        """发送 Markdown 消息给指定用户."""
        return await self._send_message({
            "touser": user_id,
            "msgtype": "markdown",
            "agentid": self._agent_id,
            "markdown": {"content": content},
        })
