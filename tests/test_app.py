"""Tests for app — FastAPI 路由（健康检查 + 企微回调）."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.c3_push.wechat_callback import WechatCallbackCrypto


# ───────── Fixtures ─────────

_TOKEN = "test_token_123"
_ENCODING_AES_KEY = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
_CORP_ID = "wx1234567890abcdef"


@pytest.fixture()
def crypto() -> WechatCallbackCrypto:
    return WechatCallbackCrypto(_TOKEN, _ENCODING_AES_KEY, _CORP_ID)


@pytest.fixture()
def client(crypto: WechatCallbackCrypto) -> TestClient:
    """创建 TestClient，mock 掉 _get_crypto 返回测试用的加解密器."""
    with patch("src.app._get_crypto", return_value=crypto):
        from src.app import app

        with TestClient(app) as c:
            yield c


# ───────── 健康检查 ─────────


def test_health_check(client: TestClient) -> None:
    """GET /health 返回 200 和 status=ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ───────── 企微回调 GET 验证 ─────────


def test_wechat_callback_verify(
    client: TestClient, crypto: WechatCallbackCrypto
) -> None:
    """GET /wechat/callback 正确解密并返回 echostr."""
    echostr_plain = "echo_string_for_verify"
    echostr_enc = crypto.encrypt(echostr_plain)
    ts, nonce = "1409659813", "nonce_test"
    sig = crypto._sign(ts, nonce, echostr_enc)

    resp = client.get(
        "/wechat/callback",
        params={
            "msg_signature": sig,
            "timestamp": ts,
            "nonce": nonce,
            "echostr": echostr_enc,
        },
    )
    assert resp.status_code == 200
    assert resp.text == echostr_plain


def test_wechat_callback_verify_bad_signature(client: TestClient) -> None:
    """GET /wechat/callback 签名错误时返回 verify failed."""
    resp = client.get(
        "/wechat/callback",
        params={
            "msg_signature": "bad_sig",
            "timestamp": "123",
            "nonce": "n",
            "echostr": "enc",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "verify failed"


# ───────── 企微回调 POST 消息 ─────────


def test_wechat_callback_receive(
    client: TestClient, crypto: WechatCallbackCrypto
) -> None:
    """POST /wechat/callback 解密消息并调用 dispatcher."""
    inner_xml = (
        "<xml><ToUserName>corp</ToUserName>"
        "<FromUserName>user1</FromUserName>"
        "<CreateTime>1409659813</CreateTime>"
        "<MsgType>text</MsgType>"
        "<Content>开始筛选</Content></xml>"
    )
    encrypted = crypto.encrypt(inner_xml)
    ts, nonce = "1409659813", "nonce_post"
    sig = crypto._sign(ts, nonce, encrypted)

    post_xml = (
        f"<xml><Encrypt>{encrypted}</Encrypt>"
        f"<MsgSignature>{sig}</MsgSignature>"
        f"<TimeStamp>{ts}</TimeStamp>"
        f"<Nonce>{nonce}</Nonce></xml>"
    )

    with patch("src.app._dispatch_message", new_callable=AsyncMock) as mock_dispatch:
        resp = client.post(
            "/wechat/callback",
            content=post_xml,
            params={
                "msg_signature": sig,
                "timestamp": ts,
                "nonce": nonce,
            },
        )
        assert resp.status_code == 200
        assert resp.text == "success"

        mock_dispatch.assert_awaited_once()
        call_arg = mock_dispatch.call_args[0][0]
        assert call_arg["content"] == "开始筛选"
        assert call_arg["from_user"] == "user1"


def test_wechat_callback_receive_bad_decrypt(client: TestClient) -> None:
    """POST /wechat/callback 解密失败时返回 decrypt failed."""
    resp = client.post(
        "/wechat/callback",
        content="<xml><Encrypt>bad</Encrypt></xml>",
        params={
            "msg_signature": "bad",
            "timestamp": "123",
            "nonce": "n",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "decrypt failed"


# ───────── 任务状态查询 ─────────


def test_task_status_not_found(client: TestClient) -> None:
    """GET /tasks/{id} 不存在的任务返回 error."""
    resp = client.get("/tasks/nonexistent")
    assert resp.status_code == 200
    assert resp.json()["error"] == "task not found"
