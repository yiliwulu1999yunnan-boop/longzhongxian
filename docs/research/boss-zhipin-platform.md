# Boss直聘平台能力调研

## 1. 开放平台 / 企业 API

### 公开 API

**结论：Boss直聘没有公开的开放平台**

- `open.zhipin.com` 域名不存在
- 没有类似阿里云开放平台那样的公开 API 平台
- 所有 `/wapi/` 接口均为内部 SPA 调用，未对外公开

### 逆向 API（开源社区发现，非官方）

多个开源项目通过抓包逆向分析发现了 Boss直聘的内部 API 结构，可用于自动化操作。以下是已知的主要 API 端点：

#### 基础 URL
- 主站：`https://www.zhipin.com`
- Web API 前缀：`/wapi/`

#### 求职端（Geek）API

| 接口路径 | 方法 | 说明 |
|---------|------|------|
| `/wapi/zpgeek/search/joblist.json` | GET | 职位搜索列表 |
| `/wapi/zpgeek/job/card.json` | GET | 职位卡片信息 |
| `/wapi/zpgeek/job/detail.json` | GET | 职位详情 |
| `/wapi/zpgeek/history/joblist.json` | GET | 浏览历史 |
| `/wapi/zpuser/wap/getUserInfo.json` | GET | 用户信息 |
| `/wapi/zpgeek/resume/baseinfo/query.json` | GET | 简历基本信息 |
| `/wapi/zpgeek/resume/expect/query.json` | GET | 求职期望 |
| `/wapi/zpgeek/resume/status.json` | GET | 简历状态 |
| `/wapi/zprelation/resume/geekDeliverList` | GET | 已投递职位列表 |
| `/wapi/zpinterview/geek/interview/data.json` | GET | 面试数据 |
| `/wapi/zprelation/friend/getGeekFriendList.json` | POST | 已沟通联系人列表 |
| `/wapi/zpgeek/friend/add.json` | POST | 添加好友/打招呼 |
| `/wapi/zprelation/interaction/geekGetJob` | POST | 获取职位（沟通过程中） |

#### 登录认证 API

| 接口路径 | 方法 | 说明 |
|---------|------|------|
| `/wapi/zppassport/captcha/randkey` | GET | 获取验证码随机密钥 |
| `/wapi/zpweixin/qrcode/getqrcode` | GET | 获取二维码 |
| `/wapi/zppassport/qrcode/scan` | POST | 扫码状态查询 |
| `/wapi/zppassport/qrcode/scanLogin` | POST | 扫码登录确认 |
| `/wapi/zppassport/qrcode/dispatcher` | GET | 二维码调度 |

#### 认证所需 Cookie

逆向分析发现认证需要以下 Cookie：
- `__zp_stoken__`（核心认证令牌）
- `wt2`
- `wbg`
- `zp_at`

### robots.txt 禁止爬取的路径

根据 `https://www.zhipin.com/robots.txt`：

```
User-agent: *
Disallow: /*?query=*
Disallow: /*?ka=*
Disallow: /*.js*
Disallow: /job_detail/l*.html
Disallow: *?position=*
Disallow: /sem/*
Disallow: /user/sem*
Disallow: /wapi/zpaso/*/sem*
Disallow: /brand/*
Disallow: /wapi/zppassport/get/zpToken*
Disallow: /wapi/zpchat/wechat/hasBadge*
Disallow: /wapi/zpitem/web/geekVip/getSubscribeYellow*
Disallow: /wapi/zpuser/countryCode*
Disallow: /*?from=*
Disallow: /?ivk_sa=*
Disallow: /*?key=*
Disallow: /?scity=*
Disallow: /?page=*
Disallow: /web/boss/*
Disallow: /web/geek/guide*
Disallow: /web/geek/recommend*
Disallow: /*?medium=*
Disallow: /*?ref=*
Disallow: /*?frozen=*
Disallow: /web/geek/job-recommend*
Disallow: *?utm_source=*
Disallow: *?pkn=*
Disallow: /job_pk/*
```

**关键禁止项解读**：
- 搜索结果页（query, ka 参数）禁止爬取
- JS 文件禁止爬取
- 特定 API 路径禁止爬取
- 推荐相关页面禁止爬取

### 企业级服务（需联系销售获取）

**根据用户确认：Boss直聘存在企业 API，但需要联系销售并满足条件才能获取**

- 具体接入条件、费用、支持功能需联系 Boss直聘商务团队
- 企业服务电话：400-800-7000（官网可查）

### 付费产品：竞招职位·畅聊版

| 权益项 | 畅聊版配额 |
|--------|-----------|
| 每日查看简历 | 不限 |
| 每日主动沟通（打招呼） | 50次 |
| 每日回聊（回复候选人主动消息） | 不限 |
| 有效期 | 30天/单岗位 |
| 价格区间 | 108-388元/单岗位/30天（因城市而异） |

**注意**：此为招聘平台付费服务，非 API 接口。

### 与竞品对比

| 平台 | 开放平台/企业API | 批量接口服务 |
|------|------------------|--------------|
| Boss直聘 | 无（需联系销售） | 无 |
| 拉勾网 | 有 | 有 |
| 前程无忧 | 有 | 有 |

---

## 2. 反自动化措施

### 已确认的措施

| 措施类型 | 具体说明 |
|---------|---------|
| 登录验证 | 手机号 + 验证码 + **手机端人脸识别**（三步验证） |
| 简历获取流程 | 打招呼 → 双向回复 → 求简历 → 候选人同意 → 才能获取简历 |
| IP/频率限制 | 未测试，但推测存在 |
| 账号风控 | 未测试 |

### 技术检测手段（基于行业常识推断）

**前端检测可能包括：**
- 设备指纹采集（Canvas指纹、WebGL指纹、字体、屏幕分辨率、时区等）
- 浏览器特征检测（WebDriver属性、`navigator.webdriver`等Selenium特征）
- 行为分析（鼠标轨迹、键盘输入节奏、页面停留时间、点击频率）

**后端检测可能包括：**
- IP访问频率限制
- 账号行为异常检测
- 请求头完整性校验
- Cookies和Session验证
- TLS指纹检测（JA3指纹）

### 已知的反自动化机制（来自开源项目逆向分析）

根据 boss-cli 等项目的代码分析，Boss直聘的反自动化措施包括：

| 机制 | 说明 |
|------|------|
| **Cookie 过期** | `__zp_stoken__` 等认证 Cookie 会过期，需要定期刷新 |
| **Cookie TTL** | 浏览器 Cookie 有效期约 7 天，过期后需重新登录 |
| **请求频率限制** | code=9 错误码触发限流，表现为"环境异常" |
| **指数退避** | 触发限流后需要等待（10s→20s→40s→60s递增） |
| **浏览器指纹验证** | 检查 User-Agent、sec-ch-ua、DNT、Priority 等请求头 |
| **重定向检测** | 自动检测是否被重定向到登录页 |
| **IP 限制** | 频繁访问可能触发 IP 封禁 |

### 错误码说明

根据 boss-cli 项目记录的错误码：

| 错误码 | 说明 |
|--------|------|
| `not_authenticated` | 会话过期或未登录（`__zp_stoken__` 已过期） |
| `rate_limited` | 请求过于频繁（code=9） |
| `invalid_params` | 参数缺失或无效 |
| `api_error` | 上游 API 错误 |

### 开源项目反馈（供参考）

多个 GitHub 开源自动化项目反映被检测或封号：

| 项目 | 问题 |
|------|------|
| tangzhiyao/boss-show-time | 多条 issue 反映"秒封账号"、"返回403封号" |
| Cuner/boss-spider | issue 反映"存在异常行为" |
| jhcoco/bosszp | issue 反映"新版网站怕是用不了了" |
| ufownl/auto-zhipin | issue 反映"已经爬不了了" |
| YangShengzhou03/Jobs_helper | issue 反映"似乎用不了，一直显示btn挂了" |

**结论**：Boss直聘自动化风险较高，封号情况确有发生。

---

## 3. Web 端（电脑浏览器版）

### 企业后台 URL

| 页面 | URL |
|------|-----|
| 主站 | `https://www.zhipin.com` |
| 聊天推荐页（主要工作区） | `https://www.zhipin.com/web/chat/recommend` |
| 聊天列表 | `https://www.zhipin.com/web/chat/` |
| 用户中心 | `https://www.zhipin.com/web/user/` |
| 企业中心 | `https://www.zhipin.com/web/company/` |
| 简历管理 | `https://www.zhipin.com/web/resume/` |
| 消息中心 | `https://www.zhipin.com/web/message/` |

### Web 端与 App 端功能差异

| 功能 | Web 端 | App 端 |
|-----|-------|-------|
| 聊天沟通 | 完整 | 完整 |
| 搜索牛人 | 支持 | 支持 |
| 查看简历 | 支持（仅查看） | 支持（仅查看） |
| 打招呼 | 支持 | 支持 |
| 发送附件 | 不支持 | 支持 |
| 视频面试 | 不支持 | 支持 |
| 批量操作 | 不支持 | 不支持 |
| 导出简历 | 需完整流程 | 需完整流程 |

### 批量操作支持情况

- **简历列表**：无分页控件，采用无限滚动，初始加载约20张卡片
- **简历导出**：无直接导出，需完整流程（打招呼→双向回复→求简历→候选人同意）
- **批量打招呼**：不支持，需逐个操作
- **批量收藏**：不支持
- **免费版配额**：每日主动沟通3次/天，主动查看简历20个/天

### 页面技术架构

- **架构类型**：SPA + iframe 子应用（三层嵌套）
- **外层框架**：URL `/web/chat/`，使用 history.pushState API，切换导航不刷新整页
- **内容层**：通过 iframe 加载 `/web/frame/recommend/`
- **静态资源**：webpack 打包（`static/js/app.js`、`static/js/985.js`），版本号 v6183
- **技术栈**：推测 Vue.js + Webpack
- **核心接口前缀**：`/wapi/`

#### 核心接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/wapi/zpblock/recommend/major/data` | GET | 推荐候选人列表主数据 |
| `/wapi/zpblock/recommend/filters?jobId=xxx` | GET | 获取筛选条件 |
| `/wapi/zpblock/recommend/filter/remain/time` | GET | 筛选器冷却倒计时 |
| `/wapi/batch/requests` | POST | 批量合并 API 请求 |
| `/wapi/zprelation/friend/getBossFriendListV2.json` | POST | 已沟通联系人列表 |
| `/wapi/zpitem/web/chat/message/list/box` | GET | 消息列表 |

---

## 4. 结论

1. **无公开 API**：Boss直聘没有开放平台，企业无法通过程序化方式批量操作
2. **企业 API 存在但非公开**：需联系销售并满足条件才能获取，具体信息不详
3. **逆向 API 已发现但非官方**：开源社区通过抓包逆向分析出完整的 API 结构，但使用这些 API 违反平台服务条款
4. **反自动化较强**：登录需手机端人脸识别，简历获取需双向互动，自动化门槛高，封号风险确实存在
5. **Web 端功能有限**：不支持批量操作，无分页，无直接导出功能
6. **robots.txt 明确禁止爬取**：大量路径被禁止爬取，包括搜索结果页和核心 API
