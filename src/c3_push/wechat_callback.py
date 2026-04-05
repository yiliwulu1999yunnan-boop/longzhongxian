"""企业微信回调消息验证与解密.

实现企业微信回调 URL 验证（GET）和消息事件接收（POST）所需的
签名校验、AES-256-CBC 加解密逻辑。

参考：https://developer.work.weixin.qq.com/document/path/90968
"""

import base64
import hashlib
import socket
import struct
import xml.etree.ElementTree as ET

from Crypto.Cipher import AES


class CallbackCryptoError(Exception):
    """回调消息加解密失败."""


class WechatCallbackCrypto:
    """企业微信回调消息加解密器.

    Args:
        token: 回调配置中的 Token.
        encoding_aes_key: 回调配置中的 EncodingAESKey（43 字符 Base64）.
        corp_id: 企业 CorpID.
    """

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str) -> None:
        self._token = token
        self._corp_id = corp_id
        self._aes_key = base64.b64decode(encoding_aes_key + "=")
        if len(self._aes_key) != 32:
            raise CallbackCryptoError(
                f"AES key 长度应为 32 字节，实际 {len(self._aes_key)}"
            )

    # ───────── 签名 ─────────

    def _sign(self, timestamp: str, nonce: str, encrypt: str) -> str:
        """计算消息签名 = SHA1(sort([token, timestamp, nonce, encrypt]))."""
        parts = sorted([self._token, timestamp, nonce, encrypt])
        return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()

    def verify_signature(
        self, msg_signature: str, timestamp: str, nonce: str, encrypt: str
    ) -> bool:
        """校验回调签名是否匹配."""
        return self._sign(timestamp, nonce, encrypt) == msg_signature

    # ───────── PKCS#7 填充 ─────────

    @staticmethod
    def _pkcs7_pad(data: bytes, block_size: int = 32) -> bytes:
        pad_len = block_size - (len(data) % block_size)
        return data + bytes([pad_len] * pad_len)

    @staticmethod
    def _pkcs7_unpad(data: bytes) -> bytes:
        pad_len = data[-1]
        if pad_len < 1 or pad_len > 32:
            raise CallbackCryptoError(f"PKCS#7 填充无效: pad_len={pad_len}")
        return data[:-pad_len]

    # ───────── 加解密 ─────────

    def encrypt(self, plaintext: str) -> str:
        """加密明文消息，返回 Base64 编码的密文.

        格式：random(16) + msg_len(4, network order) + msg + corp_id → PKCS#7 → AES-CBC
        """
        msg_bytes = plaintext.encode("utf-8")
        corp_bytes = self._corp_id.encode("utf-8")
        random_bytes = socket.getrandrandom(16) if hasattr(socket, "getrandrandom") else __import__("os").urandom(16)
        body = random_bytes + struct.pack("!I", len(msg_bytes)) + msg_bytes + corp_bytes
        padded = self._pkcs7_pad(body)
        cipher = AES.new(self._aes_key, AES.MODE_CBC, iv=self._aes_key[:16])
        encrypted = cipher.encrypt(padded)
        return base64.b64encode(encrypted).decode("utf-8")

    def decrypt(self, ciphertext_b64: str) -> str:
        """解密 Base64 编码的密文，返回明文消息.

        Raises:
            CallbackCryptoError: 解密失败或 CorpID 不匹配.
        """
        try:
            ciphertext = base64.b64decode(ciphertext_b64)
        except Exception as exc:
            raise CallbackCryptoError(f"Base64 解码失败: {exc}") from exc

        cipher = AES.new(self._aes_key, AES.MODE_CBC, iv=self._aes_key[:16])
        try:
            decrypted = cipher.decrypt(ciphertext)
        except Exception as exc:
            raise CallbackCryptoError(f"AES 解密失败: {exc}") from exc

        unpadded = self._pkcs7_unpad(decrypted)

        # random(16) + msg_len(4) + msg + corp_id
        msg_len = struct.unpack("!I", unpadded[16:20])[0]
        msg = unpadded[20 : 20 + msg_len].decode("utf-8")
        from_corp_id = unpadded[20 + msg_len :].decode("utf-8")

        if from_corp_id != self._corp_id:
            raise CallbackCryptoError(
                f"CorpID 不匹配: 期望 {self._corp_id}，实际 {from_corp_id}"
            )
        return msg

    # ───────── 回调处理 ─────────

    def decrypt_callback_verify(
        self, msg_signature: str, timestamp: str, nonce: str, echostr: str
    ) -> str:
        """处理回调 URL 验证请求（GET），返回解密后的 echostr.

        Raises:
            CallbackCryptoError: 签名校验或解密失败.
        """
        if not self.verify_signature(msg_signature, timestamp, nonce, echostr):
            raise CallbackCryptoError("回调验证签名不匹配")
        return self.decrypt(echostr)

    def decrypt_message(
        self, msg_signature: str, timestamp: str, nonce: str, post_data: str
    ) -> str:
        """解密回调 POST 消息体（XML），返回解密后的 XML 字符串.

        Raises:
            CallbackCryptoError: 签名校验、XML 解析或解密失败.
        """
        try:
            root = ET.fromstring(post_data)
        except ET.ParseError as exc:
            raise CallbackCryptoError(f"XML 解析失败: {exc}") from exc

        encrypt_node = root.find("Encrypt")
        if encrypt_node is None or not encrypt_node.text:
            raise CallbackCryptoError("XML 中缺少 Encrypt 节点")

        encrypt_text = encrypt_node.text
        if not self.verify_signature(msg_signature, timestamp, nonce, encrypt_text):
            raise CallbackCryptoError("消息签名不匹配")

        return self.decrypt(encrypt_text)


def parse_text_message(decrypted_xml: str) -> dict[str, str]:
    """从解密后的 XML 中提取文本消息的关键字段.

    Returns:
        包含 to_user, from_user, create_time, msg_type, content 的字典.
    """
    root = ET.fromstring(decrypted_xml)
    return {
        "to_user": root.findtext("ToUserName", ""),
        "from_user": root.findtext("FromUserName", ""),
        "create_time": root.findtext("CreateTime", ""),
        "msg_type": root.findtext("MsgType", ""),
        "content": root.findtext("Content", ""),
    }
