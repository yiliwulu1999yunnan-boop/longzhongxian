"""端到端测试 — 企微加密消息 → FastAPI → dispatcher → task_queue 路由链."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.c3_push.wechat_callback import WechatCallbackCrypto

_TOKEN = "test_token_123"
_ENCODING_AES_KEY = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
_CORP_ID = "wx1234567890abcdef"


@pytest.fixture()
def crypto() -> WechatCallbackCrypto:
    return WechatCallbackCrypto(_TOKEN, _ENCODING_AES_KEY, _CORP_ID)


@pytest.fixture()
def client(crypto: WechatCallbackCrypto) -> TestClient:
    """TestClient，mock crypto 但保留真实 dispatcher 链路."""
    with patch("src.app._get_crypto", return_value=crypto):
        from src.app import app

        with TestClient(app) as c:
            yield c


def _make_post(
    crypto: WechatCallbackCrypto,
    content: str,
    from_user: str = "shop_mgr_01",
) -> tuple[str, dict[str, str]]:
    """构造加密 POST 请求体和查询参数."""
    inner_xml = (
        f"<xml><ToUserName>corp</ToUserName>"
        f"<FromUserName>{from_user}</FromUserName>"
        f"<CreateTime>1409659813</CreateTime>"
        f"<MsgType>text</MsgType>"
        f"<Content>{content}</Content></xml>"
    )
    encrypted = crypto.encrypt(inner_xml)
    ts, nonce = "1409659813", "nonce_e2e"
    sig = crypto._sign(ts, nonce, encrypted)
    post_xml = (
        f"<xml><Encrypt>{encrypted}</Encrypt>"
        f"<MsgSignature>{sig}</MsgSignature>"
        f"<TimeStamp>{ts}</TimeStamp>"
        f"<Nonce>{nonce}</Nonce></xml>"
    )
    params = {"msg_signature": sig, "timestamp": ts, "nonce": nonce}
    return post_xml, params


# ───────── 筛选指令 ─────────


def test_e2e_screening_routes_to_queue(
    client: TestClient, crypto: WechatCallbackCrypto
) -> None:
    """「筛选候选人」→ task_queue.submit 被调用，参数含 _run_screening_task."""
    body, params = _make_post(crypto, "筛选候选人")
    with patch("src.app.task_queue") as mock_queue:
        mock_queue.submit = AsyncMock(return_value="task_001")
        resp = client.post("/wechat/callback", content=body, params=params)

    assert resp.status_code == 200
    assert resp.text == "success"
    mock_queue.submit.assert_awaited_once()
    args, kwargs = mock_queue.submit.call_args
    assert args[0].__name__ == "_run_screening_task"
    assert args[1] == "shop_mgr_01"
    assert kwargs["account_id"] == "shop_mgr_01"


def test_e2e_screening_short_form(
    client: TestClient, crypto: WechatCallbackCrypto
) -> None:
    """「筛选」短指令同样路由到 screening."""
    body, params = _make_post(crypto, "筛选")
    with patch("src.app.task_queue") as mock_queue:
        mock_queue.submit = AsyncMock(return_value="task_002")
        resp = client.post("/wechat/callback", content=body, params=params)

    assert resp.status_code == 200
    mock_queue.submit.assert_awaited_once()
    args, _ = mock_queue.submit.call_args
    assert args[0].__name__ == "_run_screening_task"


# ───────── 打招呼指令 ─────────


def test_e2e_greeting_routes_to_queue(
    client: TestClient, crypto: WechatCallbackCrypto
) -> None:
    """「发1、3」→ task_queue.submit 被调用，参数含 _run_greeting_task."""
    body, params = _make_post(crypto, "发1、3")
    with patch("src.app.task_queue") as mock_queue:
        mock_queue.submit = AsyncMock(return_value="task_003")
        resp = client.post("/wechat/callback", content=body, params=params)

    assert resp.status_code == 200
    mock_queue.submit.assert_awaited_once()
    args, kwargs = mock_queue.submit.call_args
    assert args[0].__name__ == "_run_greeting_task"
    assert args[1] == "shop_mgr_01"
    assert args[2] == "发1、3"
    assert kwargs["account_id"] == "shop_mgr_01"


def test_e2e_greeting_send_all(
    client: TestClient, crypto: WechatCallbackCrypto
) -> None:
    """「全发」同样路由到 greeting."""
    body, params = _make_post(crypto, "全发")
    with patch("src.app.task_queue") as mock_queue:
        mock_queue.submit = AsyncMock(return_value="task_004")
        resp = client.post("/wechat/callback", content=body, params=params)

    assert resp.status_code == 200
    mock_queue.submit.assert_awaited_once()
    args, _ = mock_queue.submit.call_args
    assert args[0].__name__ == "_run_greeting_task"


# ───────── 分析指令 ─────────


def test_e2e_analyze_routes_to_queue(
    client: TestClient, crypto: WechatCallbackCrypto
) -> None:
    """「分析候选人张三」→ task_queue.submit 被调用，参数含 _run_analyze_task."""
    body, params = _make_post(crypto, "分析候选人张三")
    with patch("src.app.task_queue") as mock_queue:
        mock_queue.submit = AsyncMock(return_value="task_005")
        resp = client.post("/wechat/callback", content=body, params=params)

    assert resp.status_code == 200
    mock_queue.submit.assert_awaited_once()
    args, kwargs = mock_queue.submit.call_args
    assert args[0].__name__ == "_run_analyze_task"
    assert args[1] == "shop_mgr_01"
    assert args[2] == "张三"
    assert kwargs["account_id"] == "shop_mgr_01"


# ───────── 未知指令 — 不提交任务 ─────────


def test_e2e_unknown_no_task(
    client: TestClient, crypto: WechatCallbackCrypto
) -> None:
    """未知指令不触发 task_queue.submit."""
    body, params = _make_post(crypto, "今天天气怎么样")
    with patch("src.app.task_queue") as mock_queue:
        mock_queue.submit = AsyncMock()
        resp = client.post("/wechat/callback", content=body, params=params)

    assert resp.status_code == 200
    assert resp.text == "success"
    mock_queue.submit.assert_not_awaited()


# ───────── GET 回调验证（真实加解密） ─────────


def test_e2e_get_verify_real_crypto(
    client: TestClient, crypto: WechatCallbackCrypto
) -> None:
    """GET /wechat/callback 全链路加解密验证."""
    echostr_plain = "verify_echostr_20260406"
    echostr_enc = crypto.encrypt(echostr_plain)
    ts, nonce = "1409659813", "nonce_verify"
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
