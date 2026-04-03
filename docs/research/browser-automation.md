# 浏览器自动化框架对比调研

> 调研日期：2026-04-03

---

## 一、框架概览

| 框架 | 维护方 | 语言绑定 | 最新版本 | 诞生时间 |
|------|--------|----------|----------|----------|
| **Playwright** | 微软 | Python/JS/TS/Go | v1.50+ | 2020 |
| **Puppeteer** | Google | JavaScript/TypeScript | v24+ | 2017 |
| **Selenium** | Selenium Team | 全语言 | v4.25+ | 2004 |
| **Browser Use** | 社区开源 | Python | v0.2+ | 2024 |
| **DrissionPage** | 社区开源 | Python | v4.x | 2022 |
| **Cypress** | Cypress.io | JavaScript/TypeScript | v13+ | 2015 |

---

## 二、详细对比

### Playwright（微软）

| 维度 | 情况 |
|------|------|
| **WSL 支持** | ✅ 原生支持 WSL2，可直接运行 Chromium |
| **Chromium/Chrome** | ✅ 内置，支持 Chromium + Firefox + WebKit |
| **反检测能力** | 中等。默认 headless 会被检测，可通过 `webdriver` 属性掩锁、`stealth` 插件辅助，但对抗严格站点（如 Twitter、Cloudflare）仍需额外配置 |
| **登录态保持 / Cookie 管理** | ✅ 完美支持。`storageState` 可导出/导入登录态，持久化 Cookie 和 LocalStorage |
| **多账号并发** | ✅ 支持。每个 context 独立隔离，天然支持多账号并发 |
| **社区活跃度** | ★★★★★ 非常活跃，文档优秀，GitHub Stars 60k+ |
| **中文成功案例** | 大量。国内爬虫/自动化社区广泛使用，掘金、CSDN 有大量教程 |

---

### Puppeteer（Google）

| 维度 | 情况 |
|------|------|
| **WSL 支持** | ✅ 支持，WSL2 环境下可直接运行（需配合 Linux Chromium） |
| **Chromium/Chrome** | ✅ 仅 Chromium（无 Firefox/WebKit） |
| **反检测能力** | 较弱。默认 Headless 模式极易被检测，需配合 `puppeteer-extra-stealth` 插件 |
| **登录态保持 / Cookie 管理** | ✅ 支持，通过 Cookie 持久化实现 |
| **多账号并发** | ✅ 支持，每个 browser instance 独立 |
| **社区活跃度** | ★★★★☆ 活跃，文档清晰，GitHub Stars 95k+ |
| **中文成功案例** | 非常多，是国内爬虫入门首选 |

---

### Selenium

| 维度 | 情况 |
|------|------|
| **WSL 支持** | ✅ 支持（需安装 ChromeDriver 匹配版本） |
| **Chromium/Chrome** | ✅ 支持 Chrome/Edge（Chromium 内核） |
| **反检测能力** | 最弱。Selenium WebDriver 特征极其明显，极易被检测，一般需配合 undetected-chromedriver 使用 |
| **登录态保持 / Cookie 管理** | ✅ 支持，Cookie 持久化 |
| **多账号并发** | ✅ 支持，但配置相对繁琐 |
| **社区活跃度** | ★★★★☆ 非常成熟，生态庞大，文档完善，Stars 28k+ |
| **中文成功案例** | 极多，传统自动化测试事实标准 |

---

### Browser Use（AI Agent 框架）

| 维度 | 情况 |
|------|------|
| **定位** | 专为 AI Agent 设计的浏览器自动化框架，让 LLM 能够"看"网页并执行操作 |
| **WSL 支持** | ✅ 支持，基于 Playwright 实现 |
| **Chromium/Chrome** | ✅ 使用 Playwright 的 Chromium |
| **反检测能力** | 继承 Playwright 的中等水平 |
| **登录态保持 / Cookie 管理** | ✅ 支持 Playwright 的 storageState |
| **多账号并发** | ✅ 支持，天然支持多 Agent 并发 |
| **社区活跃度** | ★★★☆☆ 较新，2024 年崛起，GitHub Stars 20k+，增长迅速 |
| **中文成功案例** | 较少，中文资料主要靠社区翻译 |

---

### DrissionPage（国产新秀）

| 维度 | 情况 |
|------|------|
| **定位** | 国产框架，结合 Selenium 和 requests 的优点，支持网页端和接口双模式 |
| **WSL 支持** | ✅ 支持 |
| **Chromium/Chrome** | ✅ 支持，可无缝切换无头/有头模式 |
| **反检测能力** | ★★★★☆ 较强，专为对抗国内网站设计（淘宝、抖音等） |
| **登录态保持 / Cookie 管理** | ✅ 支持 |
| **多账号并发** | ✅ 支持 |
| **社区活跃度** | ★★★☆☆ 国内社区增长快，文档有中文 |
| **中文成功案例** | ★★★★☆ 针对国内主流网站（知乎、微博、B站等）有成功实践 |

---

### Cypress

| 维度 | 情况 |
|------|------|
| **WSL 支持** | ⚠️ 支持有限，Cypress 在 WSL 中需要特殊配置 |
| **Chromium/Chrome** | ✅ Chromium 内核（Chrome/Edge） |
| **反检测能力** | 较弱，主要面向测试而非爬虫 |
| **登录态保持 / Cookie 管理** | ✅ 支持 |
| **多账号并发** | ⚠️ 支持受限，Cypress 设计为单例模式 |
| **社区活跃度** | ★★★★☆ 活跃，面向前端测试 |
| **中文成功案例** | 较多，前端测试领域 |

---

## 三、综合推荐

| 场景 | 推荐框架 |
|------|----------|
| **国内网站自动化（反检测优先）** | DrissionPage |
| **AI Agent 网页操控** | Browser Use |
| **通用网页自动化 + 多语言** | Playwright |
| **轻量级爬虫 / JS 生态** | Puppeteer |
| **传统企业自动化测试** | Selenium |
