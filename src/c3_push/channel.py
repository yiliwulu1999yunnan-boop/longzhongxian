"""推送通道抽象接口 — V1 企业微信实现，预留飞书等扩展."""

from abc import ABC, abstractmethod

from src.c3_push.wechat_client import WechatClient


class PushChannel(ABC):
    """推送通道抽象基类."""

    @abstractmethod
    async def send_text(self, user_id: str, content: str) -> None:
        """发送纯文本消息."""

    @abstractmethod
    async def send_markdown(self, user_id: str, content: str) -> None:
        """发送 Markdown 富文本消息."""


class WechatPushChannel(PushChannel):
    """企业微信推送通道实现."""

    def __init__(self, client: WechatClient | None = None) -> None:
        self._client = client or WechatClient()

    async def send_text(self, user_id: str, content: str) -> None:
        await self._client.send_text(user_id, content)

    async def send_markdown(self, user_id: str, content: str) -> None:
        await self._client.send_markdown(user_id, content)
