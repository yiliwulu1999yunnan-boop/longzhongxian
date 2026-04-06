"""环境检查脚本 — 验证 PostgreSQL、DeepSeek API、企业微信 access_token."""

import asyncio
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.common.config import get_settings  # noqa: E402


def _header(title: str) -> None:
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")


async def check_postgres(database_url: str) -> bool:
    """检查 PostgreSQL 连接."""
    _header("PostgreSQL 连接检查")

    if not database_url:
        print("❌ DATABASE_URL 未配置")
        return False

    # 显示脱敏的连接串
    safe_url = database_url.split("@")[-1] if "@" in database_url else database_url
    print(f"  连接目标: ...@{safe_url}")

    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.text import text

        engine = create_async_engine(database_url, echo=False)
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"  ✅ 连接成功")
            print(f"  版本: {version}")
        await engine.dispose()
        return True
    except Exception as e:
        print(f"  ❌ 连接失败: {e}")
        return False


async def check_deepseek(api_key: str, base_url: str) -> bool:
    """检查 DeepSeek API Key 有效性（发送最小请求）."""
    _header("DeepSeek API 检查")

    if not api_key:
        print("❌ DEEPSEEK_API_KEY 未配置")
        return False

    print(f"  API Key: {api_key[:8]}...{api_key[-4:]}")
    print(f"  Base URL: {base_url}")

    try:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 5,
                },
            )

            if resp.status_code == 200:
                data = resp.json()
                model = data.get("model", "unknown")
                print(f"  ✅ API 调用成功")
                print(f"  模型: {model}")
                return True
            elif resp.status_code == 401:
                print(f"  ❌ API Key 无效 (401 Unauthorized)")
                return False
            else:
                print(f"  ❌ API 返回异常: {resp.status_code} {resp.text[:200]}")
                return False
    except Exception as e:
        print(f"  ❌ 请求失败: {e}")
        return False


async def check_wechat(corp_id: str, secret: str) -> bool:
    """检查企业微信 access_token 获取."""
    _header("企业微信 access_token 检查")

    if not corp_id or not secret:
        print("❌ WECHAT_CORP_ID 或 WECHAT_SECRET 未配置")
        return False

    print(f"  企业ID: {corp_id[:4]}...{corp_id[-4:]}" if len(corp_id) > 8 else f"  企业ID: {corp_id}")

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                params={"corpid": corp_id, "corpsecret": secret},
            )
            resp.raise_for_status()
            data = resp.json()

        errcode = data.get("errcode", 0)
        if errcode == 0:
            token = data.get("access_token", "")
            print(f"  ✅ 获取 access_token 成功")
            print(f"  Token: {token[:10]}...（有效期 {data.get('expires_in', '?')} 秒）")
            return True
        else:
            print(f"  ❌ 获取失败: [{errcode}] {data.get('errmsg', 'unknown')}")
            return False
    except Exception as e:
        print(f"  ❌ 请求失败: {e}")
        return False


async def main() -> None:
    print("笼中仙 AI 招聘助手 — 环境检查")
    print(f"配置文件: .env.local")

    settings = get_settings()

    results = await asyncio.gather(
        check_postgres(settings.database_url),
        check_deepseek(settings.deepseek_api_key, settings.deepseek_base_url),
        check_wechat(settings.wechat_corp_id, settings.wechat_secret),
    )

    _header("检查结果汇总")
    names = ["PostgreSQL", "DeepSeek API", "企业微信"]
    all_ok = True
    for name, ok in zip(names, results):
        status = "✅ 通过" if ok else "❌ 未通过"
        print(f"  {name}: {status}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("🎉 所有环境检查通过！可以开始联调。")
    else:
        print("⚠️  有未通过的检查项，请按上方提示修复后重新运行。")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
