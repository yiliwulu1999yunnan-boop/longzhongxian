# Lessons Learned

> Claude 犯错后记录到这里，防止重复犯同样的错。
> 反复出现的模式提炼进 CLAUDE.md。
> 此文件签入 Git，团队共享。

## 记录格式

| 日期 | 错误描述 | 正确做法 | 已提炼到 CLAUDE.md |
|------|---------|---------|-------------------|
| （示例）2026-04-03 | Claude 在修 C1 时顺手改了 C3 的推送格式 | 每次只改当前任务涉及的文件 | ✅ 已加入禁止事项 |
| 2026-04-05 | Boss storageState 当天复用验证：从 Edge DevTools 导出 Cookie → Playwright headless 加载 → URL 停留在 /web/boss/recommend，未跳转登录页 ✅ 成功 | 从浏览器 DevTools 导出 storageState 可行；需注意 sameSite 字段大小写修正（浏览器导出 "lax"，Playwright 要求 "Lax"），已在 BrowserManager._normalize_storage_state 中处理 | ❌ |
| 2026-04-05 | Playwright 新开浏览器直接访问 Boss 直聘会触发风控（反复跳转无法登录） | 不要用 Playwright 新浏览器登录 Boss 直聘，应从已登录的日常浏览器导出 storageState | ❌ |
| 2026-04-05 | Boss 直聘推荐页加载后会发生 SPA 路由跳转，导致 page.title() 报 "Execution context was destroyed" | 在 Boss 页面操作时用 wait_for_load_state 或 try/except 处理导航导致的上下文销毁 | ❌ |
| 2026-04-05 | Boss 直聘推荐牛人页面 URL 是 /web/chat/recommend，不是 /web/boss/recommend | 已修正 BrowserManager.BOSS_RECOMMEND_URL | ❌ |
| 2026-04-05 | 【严重】Playwright 启动新浏览器加载导出的 Cookie 访问 Boss 直聘，会被检测为异常登录，触发安全机制强制登出所有设备（包括用户正在使用的 Edge） | 绝不能用 Playwright launch() 新浏览器 + storageState 方式访问 Boss 直聘。应使用 connect_over_cdp() 连接用户已打开的浏览器，避免被识别为新设备 | ❌ |
| 2026-04-05 | cookieStore.getAll() 无法获取 httpOnly Cookie，导出的 storageState 不完整，认证会失败 | 使用 Cookie-Editor 扩展导出完整 Cookie（包含 httpOnly） | ❌ |
| 2026-04-07 | CDP 模式下 new_page() 创建新标签页，Boss 直聘检测到自动化指纹，强制登出账号 | CDP 模式必须复用 context.pages[0]（用户已有的标签页），不能 new_page()；退出时也不关闭复用页面 | ❌ |

## 规则

- Claude 犯错被纠正后，立即在这里追加一行
- 每周审查一次，把反复出现的模式提炼进 CLAUDE.md
- 提炼后在"已提炼"列标记 ✅，原记录保留不删除
