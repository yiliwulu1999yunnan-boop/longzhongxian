"""Tests for c3_push — wechat_client, wechat_callback, channel."""

import hashlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.c3_push.wechat_callback import (
    CallbackCryptoError,
    WechatCallbackCrypto,
    parse_text_message,
)
from src.c3_push.wechat_client import WechatClient, WechatClientError
from src.c3_push.channel import PushChannel, WechatPushChannel


# ───────── Fixtures ─────────

# 官方测试向量风格的固定参数
_TOKEN = "test_token_123"
_ENCODING_AES_KEY = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
_CORP_ID = "wx1234567890abcdef"


@pytest.fixture()
def crypto() -> WechatCallbackCrypto:
    return WechatCallbackCrypto(_TOKEN, _ENCODING_AES_KEY, _CORP_ID)


# ───────── WechatCallbackCrypto 签名 ─────────


def test_verify_signature(crypto: WechatCallbackCrypto) -> None:
    """签名校验：正确签名返回 True."""
    ts, nonce, encrypt = "1409659813", "nonce123", "encrypted_data"
    parts = sorted([_TOKEN, ts, nonce, encrypt])
    expected = hashlib.sha1("".join(parts).encode()).hexdigest()
    assert crypto.verify_signature(expected, ts, nonce, encrypt)


def test_verify_signature_mismatch(crypto: WechatCallbackCrypto) -> None:
    """签名校验：错误签名返回 False."""
    assert not crypto.verify_signature("bad_sig", "123", "nonce", "enc")


# ───────── 加解密往返 ─────────


def test_encrypt_decrypt_roundtrip(crypto: WechatCallbackCrypto) -> None:
    """加密后解密应还原原文."""
    plaintext = "<xml><Content>你好世界</Content></xml>"
    encrypted = crypto.encrypt(plaintext)
    decrypted = crypto.decrypt(encrypted)
    assert decrypted == plaintext


def test_decrypt_wrong_corp_id() -> None:
    """解密时 CorpID 不匹配应抛出异常."""
    crypto_a = WechatCallbackCrypto(_TOKEN, _ENCODING_AES_KEY, "corp_a")
    crypto_b = WechatCallbackCrypto(_TOKEN, _ENCODING_AES_KEY, "corp_b")
    encrypted = crypto_a.encrypt("hello")
    with pytest.raises(CallbackCryptoError, match="CorpID 不匹配"):
        crypto_b.decrypt(encrypted)


def test_decrypt_bad_base64(crypto: WechatCallbackCrypto) -> None:
    """非法 Base64 输入应抛出异常."""
    with pytest.raises(CallbackCryptoError, match="Base64 解码失败"):
        crypto.decrypt("!!!not-base64!!!")


# ───────── 回调 URL 验证 ─────────


def test_callback_verify(crypto: WechatCallbackCrypto) -> None:
    """回调 URL 验证：签名正确时返回解密后的 echostr."""
    echostr_plain = "echo_test_string"
    echostr_enc = crypto.encrypt(echostr_plain)
    ts, nonce = "1409659813", "nonce456"
    sig = crypto._sign(ts, nonce, echostr_enc)

    result = crypto.decrypt_callback_verify(sig, ts, nonce, echostr_enc)
    assert result == echostr_plain


def test_callback_verify_bad_signature(crypto: WechatCallbackCrypto) -> None:
    """回调 URL 验证：签名错误时抛出异常."""
    with pytest.raises(CallbackCryptoError, match="签名不匹配"):
        crypto.decrypt_callback_verify("bad", "123", "nonce", "enc")


# ───────── POST 消息解密 ─────────


def test_decrypt_message(crypto: WechatCallbackCrypto) -> None:
    """POST 消息解密：从 XML 中提取并解密."""
    inner_xml = (
        "<xml><ToUserName>corp</ToUserName>"
        "<FromUserName>user1</FromUserName>"
        "<CreateTime>1409659813</CreateTime>"
        "<MsgType>text</MsgType>"
        "<Content>查看筛选报告</Content></xml>"
    )
    encrypted = crypto.encrypt(inner_xml)
    ts, nonce = "1409659813", "nonce789"
    sig = crypto._sign(ts, nonce, encrypted)

    post_xml = (
        f"<xml><Encrypt>{encrypted}</Encrypt>"
        f"<MsgSignature>{sig}</MsgSignature>"
        f"<TimeStamp>{ts}</TimeStamp>"
        f"<Nonce>{nonce}</Nonce></xml>"
    )

    result = crypto.decrypt_message(sig, ts, nonce, post_xml)
    assert "<Content>查看筛选报告</Content>" in result


def test_decrypt_message_missing_encrypt_node(
    crypto: WechatCallbackCrypto,
) -> None:
    """POST 消息体缺少 Encrypt 节点时抛出异常."""
    with pytest.raises(CallbackCryptoError, match="Encrypt"):
        crypto.decrypt_message("sig", "ts", "n", "<xml><Other>x</Other></xml>")


def test_decrypt_message_invalid_xml(crypto: WechatCallbackCrypto) -> None:
    """POST 消息体非法 XML 时抛出异常."""
    with pytest.raises(CallbackCryptoError, match="XML 解析失败"):
        crypto.decrypt_message("sig", "ts", "n", "not xml at all<<<")


# ───────── parse_text_message ─────────


def test_parse_text_message() -> None:
    """从解密后的 XML 提取文本消息字段."""
    xml = (
        "<xml><ToUserName>corp</ToUserName>"
        "<FromUserName>user1</FromUserName>"
        "<CreateTime>1409659813</CreateTime>"
        "<MsgType>text</MsgType>"
        "<Content>开始筛选</Content></xml>"
    )
    msg = parse_text_message(xml)
    assert msg["to_user"] == "corp"
    assert msg["from_user"] == "user1"
    assert msg["msg_type"] == "text"
    assert msg["content"] == "开始筛选"


# ───────── WechatClient access_token ─────────


@pytest.mark.asyncio()
async def test_get_access_token_fetches_and_caches() -> None:
    """首次调用获取 token，第二次使用缓存."""
    client = WechatClient(corp_id="cid", corp_secret="secret", agent_id="1")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "errcode": 0,
        "access_token": "token_abc",
        "expires_in": 7200,
    }
    mock_resp.raise_for_status = lambda: None

    with patch("c3_push.wechat_client.httpx.AsyncClient") as mock_cls:
        mock_client_inst = AsyncMock()
        mock_client_inst.get.return_value = mock_resp
        mock_client_inst.__aenter__ = AsyncMock(return_value=mock_client_inst)
        mock_client_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client_inst

        token1 = await client.get_access_token()
        assert token1 == "token_abc"

        # 第二次应使用缓存，不再调用 API
        token2 = await client.get_access_token()
        assert token2 == "token_abc"
        assert mock_client_inst.get.call_count == 1


@pytest.mark.asyncio()
async def test_get_access_token_error_raises() -> None:
    """access_token API 返回错误时抛出 WechatClientError."""
    client = WechatClient(corp_id="cid", corp_secret="secret", agent_id="1")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"errcode": 40013, "errmsg": "invalid corpid"}
    mock_resp.raise_for_status = lambda: None

    with patch("c3_push.wechat_client.httpx.AsyncClient") as mock_cls:
        mock_client_inst = AsyncMock()
        mock_client_inst.get.return_value = mock_resp
        mock_client_inst.__aenter__ = AsyncMock(return_value=mock_client_inst)
        mock_client_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client_inst

        with pytest.raises(WechatClientError, match="invalid corpid"):
            await client.get_access_token()


# ───────── WechatClient 消息发送 ─────────


@pytest.mark.asyncio()
async def test_send_text_message_format() -> None:
    """发送文本消息的 payload 格式正确."""
    client = WechatClient(corp_id="cid", corp_secret="secret", agent_id="100")
    # 预设 token 跳过 fetch
    client._access_token = "cached_token"
    client._token_expires_at = time.time() + 3600

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"errcode": 0, "errmsg": "ok"}
    mock_resp.raise_for_status = lambda: None

    with patch("c3_push.wechat_client.httpx.AsyncClient") as mock_cls:
        mock_client_inst = AsyncMock()
        mock_client_inst.post.return_value = mock_resp
        mock_client_inst.__aenter__ = AsyncMock(return_value=mock_client_inst)
        mock_client_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client_inst

        await client.send_text("user1", "hello")

        call_kwargs = mock_client_inst.post.call_args
        payload = call_kwargs.kwargs["json"]
        assert payload["touser"] == "user1"
        assert payload["msgtype"] == "text"
        assert payload["agentid"] == "100"
        assert payload["text"]["content"] == "hello"


@pytest.mark.asyncio()
async def test_send_markdown_message_format() -> None:
    """发送 Markdown 消息的 payload 格式正确."""
    client = WechatClient(corp_id="cid", corp_secret="secret", agent_id="100")
    client._access_token = "cached_token"
    client._token_expires_at = time.time() + 3600

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"errcode": 0, "errmsg": "ok"}
    mock_resp.raise_for_status = lambda: None

    with patch("c3_push.wechat_client.httpx.AsyncClient") as mock_cls:
        mock_client_inst = AsyncMock()
        mock_client_inst.post.return_value = mock_resp
        mock_client_inst.__aenter__ = AsyncMock(return_value=mock_client_inst)
        mock_client_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client_inst

        await client.send_markdown("user2", "# Report\n- item1")

        payload = mock_client_inst.post.call_args.kwargs["json"]
        assert payload["msgtype"] == "markdown"
        assert payload["markdown"]["content"] == "# Report\n- item1"


# ───────── Channel 抽象 ─────────


def test_push_channel_is_abstract() -> None:
    """PushChannel 不能直接实例化."""
    with pytest.raises(TypeError):
        PushChannel()  # type: ignore[abstract]


@pytest.mark.asyncio()
async def test_wechat_push_channel_delegates() -> None:
    """WechatPushChannel 委托给 WechatClient."""
    mock_client = AsyncMock(spec=WechatClient)
    channel = WechatPushChannel(client=mock_client)

    await channel.send_text("u1", "hi")
    mock_client.send_text.assert_awaited_once_with("u1", "hi")

    await channel.send_markdown("u2", "# md")
    mock_client.send_markdown.assert_awaited_once_with("u2", "# md")
