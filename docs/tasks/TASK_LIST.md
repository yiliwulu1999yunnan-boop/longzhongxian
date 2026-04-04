# Phase 1 任务清单

> **来源：** ADR-001 架构决策记录 V1.1 + Phase 1 V1 需求说明
> **拆解原则：** 每个任务卡 = 一次 Claude Code session 能稳定完成并验证
> **日期：** 2026-04-04

---

## 依赖关系总览

```
P1（基础模块）──┬──→ P2（数据库Schema+账号映射）──→ C1.1
               │                                   │
               │   P4a（岗位画像→YAML）─→ P4b（profile_loader）──→ C2.1
               │                                                    │
               ├──→ P3（企业微信接入）──→ P6（Web服务入口）──→ C3.3a
               │                                                │
               │                                                │
C1.1（浏览器上下文）→ C1.2（列表获取）→ C1.3（详情+入库）→ C1.4（C1集成测试）
                                                                │
                    C2.1（硬规则引擎）→ C2.2（LLM评估）→ C2.3（合并+快照）→ C2.4（C2集成测试）
                                                                              │
                    C3.1（报告生成）──→ C3.2（企微推送）                        │
                         │                    │                                │
                         │                    └──→ C3.3a（链路编排代码）→ C3.3b（全链路集成测试）
                         │
                         └──→ C4.1（指令解析）
                                    │
                    C4.2（打招呼自动化）──→ C4.3（配额+通知）
                                                    │
                    E2.1（聊天记录抓取）→ E2.2（汇总生成+推送）
```

### 串行 vs 并行标注

| 可并行组 | 任务 | 说明 |
|---------|------|------|
| **第一批（并行）** | P1, P4a | P1 无依赖；P4a 读文档提取规则，纯配置产出无代码依赖 |
| **第二批（P1完成后并行）** | P2, P3, P4b | P2/P3 依赖 P1；P4b 依赖 P4a + P1 |
| **第三批（P2完成后，与P6并行）** | C1.1 → C1.2 → C1.3 → C1.4 | C1 内部串行；P6 依赖 P1+P3，可与 C1 并行 |
| **第四批（C1.4 + P4b 完成后）** | C2.1 → C2.2 → C2.3 → C2.4 | C2 内部串行，C2.1 和 C2.2 可并行 |
| **第五批（C2.4 + P3 完成后）** | C3.1 → C3.2 → C3.3a → C3.3b | C3 内部串行；C3.3a 还依赖 P6 |
| **第六批（C3.1 完成后即可启动）** | C4.1 → C4.3 | C4.1 只需报告编号格式约定；C4.2 可与 C4.1 并行 |
| **第七批（C4.3 完成后）** | E2.1 → E2.2 | E2 优先级最低，复用 C1 能力 |

> C3.1（报告生成）可以与 C2 并行开发——只要约定好 C2 的输出数据结构即可。
> C4.1（指令解析）依赖 C3.1 的候选人编号格式约定，不依赖完整链路编排。
> C4.2（打招呼自动化）只依赖 C1.1 + C1.3 + P4a，可与 C4.1 并行开发。

---

## 前置任务

---

# 任务卡：P1 Common 基础模块（配置加载 + 日志 + 数据库连接）

## 目标
搭建所有模块共享的基础设施：环境变量配置加载、结构化日志、PostgreSQL 连接池。

## 涉及范围
- 创建 `src/common/config.py` — 基于 pydantic-settings 加载 .env.local
- 创建 `src/common/db.py` — SQLAlchemy async engine + session 管理
- 创建 `src/common/logger.py` — structlog 配置，JSON 格式输出
- 修改 `src/common/__init__.py` — 导出公共接口
- 修改 `pyproject.toml` — 添加依赖（pydantic-settings, sqlalchemy[asyncio], asyncpg, structlog）

## 前置依赖
无

## 风险点
- SQLAlchemy async 需要 asyncpg 驱动，确认 Python 版本兼容性
- pydantic-settings v2 的 env 文件加载方式与 v1 不同

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：config 能正确加载 .env.example 中的所有字段
- 单元测试：DB session 能正常创建和关闭（用 SQLite 内存库测试）
- 单元测试：logger 输出符合 JSON 格式

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：P2 数据库 Schema + 账号映射

## 目标
设计并创建 Phase 1 所需的全部数据表 + 账号映射查询接口，生成 migration 文件（人工确认后执行）。

## 涉及范围
- 创建 `src/common/models.py` — SQLAlchemy ORM 模型
  - `candidates` 表（encryptGeekId 唯一键、原始 JSON、详情页 URL、来源账号、创建时间）
  - `scoring_snapshots` 表（候选人 FK、硬规则结果 JSON、LLM 原始输出、岗位画像版本、最终结论、时间戳）
  - `store_accounts` 表（企业微信 userid、门店 ID、Boss 账号 ID、storageState 路径、岗位类型、状态）
  - `operation_logs` 表（操作类型、账号、目标候选人、结果、配额消耗、时间戳）
  - `boss_jobs` 表（Boss 账号 ID、jobId、岗位名称、岗位类型、状态）——**V1 可选预留**：用于记录 Boss 直聘上每个账号发布的岗位信息，C1 抓取推荐列表时按 jobId 区分不同岗位的候选人。V1 阶段如果每个账号只关注一个岗位可暂不使用，但表结构先建好
- 创建 `alembic/` 目录 + 初始 migration
- 创建 `src/common/account_mapping.py` — 企业微信 userid → 门店 → Boss 账号 → storageState 映射查询
- 创建 `config/store_accounts.yaml` — V1 手动维护的门店配置模板
- 创建 `src/common/storage_state.py` — storageState 文件存在性检查 + 过期预警工具
- 修改 `pyproject.toml` — 添加 alembic 依赖
- 创建 `tests/test_account_mapping.py`

## 前置依赖
- P1（数据库连接 + ORM base）

## 风险点
- 候选人原始信息字段结构依赖 Boss 直聘 /wapi/ 返回的实际 JSON，V1 先用 JSONB 存原始数据，后续按需拆列
- migration 文件生成后必须人工确认再执行（CLAUDE.md 规定）
- storageState Cookie 有效期未经长期实测确认（仅验证 48h 稳定）

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：所有 model 能正常创建表结构（SQLite 内存库）
- 单元测试：给定 userid 能查到对应的 storageState 路径
- 单元测试：storageState 文件不存在或过期时返回明确错误
- alembic revision 生成成功，migration 文件可读

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：P3 企业微信应用消息接入

## 目标
封装企业微信应用消息的收发 SDK，支持接收店长文本指令 + 发送富文本消息。

## 涉及范围
- 创建 `src/c3_push/wechat_client.py` — access_token 获取与缓存、发送文本/Markdown 消息
- 创建 `src/c3_push/wechat_callback.py` — 回调 URL 验证（EncodingAESKey 解密）、接收消息事件
- 创建 `src/c3_push/channel.py` — 推送通道抽象接口（V1 企业微信实现，预留飞书）
- 修改 `pyproject.toml` — 添加依赖（httpx, pycryptodome）
- 创建 `tests/test_wechat_client.py`

## 前置依赖
- P1（配置加载——企业微信 CorpID/Secret/Token/AESKey）
- **外部依赖：** 笼中仙企业微信管理员需创建内部应用并提供 API 凭证

## 风险点
- 企业微信管理员审核流程可能超过 1 周，阻塞 C3 开发
- 备选：先用 mock/命令行模拟指令输入，企业微信就绪后替换入口层
- 回调消息解密需要 AES 256-CBC，依赖 pycryptodome

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：access_token 获取逻辑（mock HTTP）
- 单元测试：回调签名验证 + 消息解密（用官方测试向量）
- 单元测试：消息发送格式正确（mock HTTP）

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：P6 Web 服务入口（FastAPI + 企微回调路由 + 异步任务调度）

## 目标
搭建系统的 Web 服务骨架：FastAPI 应用、企业微信回调路由注册、异步任务调度基础设施。

## 涉及范围
- 创建 `src/app.py` — FastAPI 应用入口
  - 健康检查端点
  - 企业微信回调验证路由（GET，URL 验证）
  - 企业微信消息接收路由（POST，解密 → 交给 dispatcher）
- 创建 `src/common/task_queue.py` — 异步任务调度
  - 基于 asyncio 的简易任务队列（V1 不引入 Celery，单机够用）
  - 任务提交、状态查询、并发控制（同一 Boss 账号互斥锁）
- 修改 `pyproject.toml` — 添加依赖（fastapi, uvicorn）
- 创建 `tests/test_app.py` — FastAPI TestClient 测试回调路由
- 创建 `tests/test_task_queue.py`

## 前置依赖
- P1（配置加载）
- P3（企业微信回调解密逻辑——wechat_callback.py）

## 风险点
- 企业微信回调 URL 需要公网可访问，开发阶段可用 ngrok/frp 临时暴露
- 异步任务队列的并发控制需要考虑进程重启后的状态恢复（V1 可接受丢失）

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：健康检查端点返回 200
- 单元测试：企业微信回调 GET 验证正确响应 echostr
- 单元测试：企业微信消息 POST 解密成功并调用 dispatcher（mock）
- 单元测试：任务队列提交/执行/并发互斥逻辑正确

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：P4a 岗位画像文档 → YAML 配置提取

## 目标
从 `docs/job-profiles/` 中的 10 份文档提取字段级规则，产出标准化 YAML 配置文件。

## 涉及范围
- 读取 `docs/job-profiles/` 下的全部文档（只读）
- 创建 `config/job_profiles/*.yaml` — 每个岗位类型一个文件
  - 硬规则阈值：年龄范围、学历下限、薪资区间、行业关键词白名单/黑名单、红线条件
  - LLM prompt 模板：软性评估维度、岗位特殊要求描述
  - 打招呼模板消息（≤150 字）
- 创建 `config/job_profiles/_schema.yaml` — 配置文件 JSON Schema 说明
- 输出一份规则提取总结，列出每个岗位的提取完成度和待确认项

## 前置依赖
无（纯文档阅读 + YAML 产出，无代码依赖）

## 风险点
- 10 份文档格式混杂（doc/ppt/pdf/excel），信息可能不完整或不一致
- 部分岗位可能缺少明确的硬规则阈值，需要标注"待确认"让业务方补充
- 基层餐饮岗位画像可能和传统 JD 结构差异大

## 验证方式
- 每个 YAML 文件结构符合 `_schema.yaml` 定义，必填字段完整
- 规则提取总结文档完成，待确认项明确标注
- make lint 通过（YAML 语法检查）

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：P4b 岗位画像配置加载器

## 目标
实现 Python 代码层的岗位画像配置加载器，将 YAML 配置解析为类型安全的配置对象。

## 涉及范围
- 创建 `src/c2_scorer/profile_loader.py` — 岗位画像配置加载器
  - 加载指定岗位类型的 YAML 文件
  - 返回 Pydantic model（硬规则阈值 + LLM prompt 模板 + 打招呼模板）
  - 配置版本标识提取（供判断快照记录）
- 创建 `tests/test_profile_loader.py`

## 前置依赖
- P4a（YAML 配置文件已产出）
- P1（pydantic 依赖已安装）

## 风险点
- YAML 配置结构可能在 P4a 完成后需要微调，loader 需要适配

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：能正确加载每个 YAML 并返回类型安全的配置对象
- 单元测试：YAML 文件缺失或格式错误时抛出明确异常

## 回退方式
回退到本任务开始前的 commit

---

## C1：Boss 直聘简历获取

---

# 任务卡：C1.1 Playwright 浏览器上下文管理

## 目标
封装 Playwright browser context 的创建、storageState 加载、多账号隔离逻辑，提供可复用的浏览器会话管理器。

## 涉及范围
- 创建 `src/c1_scraper/browser.py` — BrowserManager 类
  - 按 storageState 文件创建隔离的 browser context
  - 页面导航到 Boss 直聘推荐列表页
  - context 生命周期管理（创建/关闭）
  - 反检测基础配置（user-agent、viewport 等）
- 修改 `pyproject.toml` — 添加 playwright 依赖
- 创建 `tests/test_browser.py`

## 前置依赖
- P1（配置加载——STORAGE_STATES_DIR 路径）
- P2（store_accounts 表 + 账号映射——根据店长 ID 找到对应 storageState）

## 风险点
- Playwright 在 Linux 服务器上需要安装浏览器二进制文件（`playwright install chromium`）
- WSL 环境下 Playwright 可能需要额外的系统依赖
- storageState 文件损坏或过期时需要优雅降级

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：能用 mock storageState 创建 browser context
- 单元测试：多个 context 互相隔离（不同 storageState）
- 单元测试：storageState 文件不存在时抛出明确异常
- **手动验证：** 用真实 Boss 直聘账号验证 storageState 导出 → 隔日复用是否有效，结果记录到 `lessons.md`（含有效期观测值、失效现象描述）

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：C1.2 推荐列表 /wapi/ 拦截 + 候选人数据解析

## 目标
通过 Playwright 网络请求拦截获取 `/wapi/zpblock/recommend/major/data` 接口返回的候选人列表 JSON，解析出结构化候选人数据。

## 涉及范围
- 创建 `src/c1_scraper/recommend_scraper.py` — 推荐列表抓取器
  - 注册 route/response 监听拦截 `/wapi/` 接口
  - 解析 JSON 响应提取候选人列表
  - 自动滚动加载更多候选人（可配置最大数量）
  - 提取每个候选人的 encryptGeekId + 详情页 URL 路径
- 创建 `src/c1_scraper/models.py` — 候选人数据 dataclass/Pydantic model
- 创建 `tests/test_recommend_scraper.py` — 用 fixture JSON 测试解析逻辑
- 创建 `tests/fixtures/wapi_recommend_response.json` — 示例接口返回数据

## 前置依赖
- C1.1（浏览器上下文管理）

## 风险点
- /wapi/ 接口返回的 JSON 结构可能变化，需要做字段缺失的防御性处理
- 无限滚动触发时机和等待策略需要调参
- 接口可能有反爬检测（频率限制），需要合理的请求间隔

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：能正确解析 fixture JSON 中的候选人列表
- 单元测试：字段缺失时不崩溃，记录日志并跳过
- 单元测试：encryptGeekId 和详情页 URL 正确提取

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：C1.3 候选人详情提取 + 去重入库

## 目标
从候选人详情面板提取完整简历信息，去重后存入数据库。

## 涉及范围
- 创建 `src/c1_scraper/detail_extractor.py` — 详情信息提取
  - 优先监听详情面板加载时的 /wapi/ 接口获取 JSON
  - DOM 解析兜底（iframe 内 `.geek-card-small` 等选择器）
  - 提取：基本信息、工作经历、教育经历、技能标签、自我评价
- 创建 `src/c1_scraper/candidate_store.py` — 候选人持久化
  - encryptGeekId 去重检查
  - 新候选人入库（原始 JSON + 结构化字段 + 详情页 URL + 来源账号）
  - 返回新增候选人列表（供 C2 打分）
- 创建 `tests/test_detail_extractor.py`
- 创建 `tests/test_candidate_store.py`

## 前置依赖
- C1.2（推荐列表数据——候选人 ID 列表）
- P2（candidates 表结构）

## 风险点
- 详情面板在三层 iframe 嵌套中（/web/frame/c-resume/），DOM 选择器可能不稳定
- 优先用接口 JSON 可以绕过 iframe 问题
- 部分候选人信息可能不完整（基层餐饮简历特点）

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：JSON 接口解析提取完整候选人信息
- 单元测试：DOM 兜底解析正确提取关键字段
- 单元测试：重复 encryptGeekId 不重复入库
- 单元测试：新增候选人正确返回供后续打分

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：C1.4 C1 模块集成测试

## 目标
验证 C1 完整链路：从 Playwright 启动 → 列表获取 → 详情提取 → 去重入库的端到端流程。

## 涉及范围
- 创建 `tests/integration/test_c1_pipeline.py` — C1 端到端测试
  - 用 Playwright 的 mock route 模拟 Boss 直聘页面和 /wapi/ 响应
  - 验证完整流程：启动 → 拦截 → 解析 → 入库
  - 验证去重：同一候选人第二次运行不重复入库
- 创建 `tests/integration/fixtures/` — mock 页面 HTML + API 响应
- 创建 `src/c1_scraper/pipeline.py` — C1 流程编排入口函数

## 前置依赖
- C1.1 + C1.2 + C1.3 全部完成

## 风险点
- Playwright mock route 需要模拟三层 iframe 结构，可能比较复杂
- 集成测试运行时间较长，需要合理设置超时

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 集成测试覆盖：正常流程、去重流程、网络异常降级流程

## 回退方式
回退到本任务开始前的 commit

---

## C2：AI 匹配打分 + 风险识别

---

# 任务卡：C2.1 硬规则引擎

## 目标
实现基于岗位画像 YAML 配置的硬规则过滤层：红线规则直接过滤、常规规则输出通过/不通过判断。

## 涉及范围
- 创建 `src/c2_scorer/hard_rules.py` — 硬规则引擎
  - 红线规则：一年内离职 3 次 → 直接"不建议"
  - 年龄范围匹配
  - 学历下限检查
  - 薪资区间匹配
  - 行业关键词白名单/黑名单粗筛
  - 每条规则独立输出判断结果（触发/未触发 + 具体数值）
- 利用 P4b 产出的 `src/c2_scorer/profile_loader.py` 加载岗位画像配置
- 创建 `tests/test_hard_rules.py` — 覆盖每条规则的边界情况

## 前置依赖
- P4b（岗位画像配置加载器）
- P2（candidates 表——读取候选人数据）

## 风险点
- 基层餐饮简历信息不完整（缺学历、缺工作时间），规则引擎需要处理字段缺失场景
- 行业关键词匹配需要考虑同义词（"火锅店" vs "餐饮"）
- 跳槽频率计算需要解析非标准的工作经历时间格式

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：红线规则触发 → 直接返回"不建议"
- 单元测试：年龄/学历/薪资边界值正确判断
- 单元测试：字段缺失时规则跳过而非崩溃，记录到判断结果中
- 单元测试：行业关键词匹配覆盖常见同义词

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：C2.2 DeepSeek V3 LLM 评估层

## 目标
实现 LLM 软性评估层：调用 DeepSeek V3 API，基于岗位画像 prompt 模板对候选人做综合匹配度评估。

## 涉及范围
- 创建 `src/c2_scorer/llm_scorer.py` — LLM 评估器
  - DeepSeek V3 API 客户端（OpenAI 兼容接口）
  - 从岗位画像 YAML 加载 prompt 模板，填入候选人信息
  - 解析 LLM 返回的 JSON 结构（评分、理由、风险标注、亮点）
  - 超时/重试/降级处理
- 修改 `pyproject.toml` — 添加 openai 依赖（DeepSeek 用 OpenAI SDK）
- 创建 `tests/test_llm_scorer.py` — mock API 响应测试解析逻辑

## 前置依赖
- P1（配置加载——DEEPSEEK_API_KEY、DEEPSEEK_BASE_URL）
- P4b（岗位画像配置加载器——LLM prompt 模板部分）

## 风险点
- LLM 返回的 JSON 格式可能不稳定，需要健壮的解析 + 重试
- DeepSeek V3 API 可能有速率限制，需要控制并发
- prompt 模板质量直接影响 80% 准确率目标，后续需要迭代

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：prompt 模板渲染正确填入候选人信息
- 单元测试：LLM 正常返回时解析出评分 + 理由 + 风险标注
- 单元测试：LLM 返回非法 JSON 时优雅降级
- 单元测试：API 超时时重试逻辑正确

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：C2.3 评分合并 + 判断快照存储

## 目标
将硬规则层和 LLM 层的结果合并为最终三档判断，并存储完整的判断快照。

## 涉及范围
- 创建 `src/c2_scorer/score_merger.py` — 评分合并器
  - 合并逻辑：硬规则红线触发 → 直接"不建议"（跳过 LLM）；硬规则通过 → 综合 LLM 结果给出三档
  - 输出：最终结论 + 风险标注列表 + 推荐理由摘要
- 创建 `src/c2_scorer/snapshot_store.py` — 判断快照持久化
  - 存储内容：候选人原始信息快照、硬规则逐项结果、LLM 原始输出、岗位画像版本、最终结论、时间戳
  - 写入 scoring_snapshots 表
- 创建 `tests/test_score_merger.py`
- 创建 `tests/test_snapshot_store.py`

## 前置依赖
- C2.1（硬规则引擎输出）
- C2.2（LLM 评估输出）
- P2（scoring_snapshots 表结构）

## 风险点
- 合并逻辑的阈值设定需要后续基于真实数据调优
- 快照数据量可能较大（每个候选人一条完整记录），需要关注存储增长

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：红线触发 → "不建议"，不调用 LLM
- 单元测试：硬规则通过 + LLM 高分 → "推荐沟通"
- 单元测试：硬规则通过 + LLM 中等 → "可以看看"
- 单元测试：快照完整存储所有字段，可反序列化

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：C2.4 C2 模块集成测试

## 目标
验证 C2 完整链路：候选人数据输入 → 硬规则过滤 → LLM 评估 → 合并输出 → 快照存储。

## 涉及范围
- 创建 `tests/integration/test_c2_pipeline.py`
  - 端到端测试：mock 候选人数据 → 硬规则 → mock LLM → 合并 → 存储
  - 准确率框架：用标注样本集评估评分质量（为后续 prompt 迭代铺路）
- 创建 `src/c2_scorer/pipeline.py` — C2 流程编排入口函数
- 创建 `tests/integration/fixtures/sample_candidates.json` — 标注样本

## 前置依赖
- C2.1 + C2.2 + C2.3 全部完成

## 风险点
- 标注样本的质量直接影响测试有效性，初期样本量有限
- LLM mock 和真实 API 行为可能有差异

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 集成测试覆盖：红线过滤场景、正常三档评分场景、LLM 异常降级场景

## 回退方式
回退到本任务开始前的 commit

---

## C3：筛选报告推送

---

# 任务卡：C3.1 筛选报告内容生成

## 目标
将 C2 的评分结果格式化为中等信息密度的筛选报告，适合店长在手机上三秒看懂。

## 涉及范围
- 创建 `src/c3_push/report_builder.py` — 报告生成器
  - 输入：本次筛选的全部候选人评分结果
  - 输出：结构化报告（总数 + 各档人数 + 推荐候选人摘要）
  - 格式：企业微信 Markdown 消息格式
  - "推荐沟通"展开摘要：脱敏姓名、核心经验、风险标注、亮点
  - "可以看看"和"不建议"只显示数字
  - 每个推荐候选人带编号（供 C4 指令引用："发1、3"）
- 创建 `tests/test_report_builder.py`

## 前置依赖
- C2.3（评分合并输出的数据结构）——需约定接口，代码可与 C2 并行开发

## 风险点
- 企业微信 Markdown 消息有字数和格式限制，需确认
- 候选人数量多时报告可能过长，需截断或分页策略

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：0 个推荐候选人时报告仍完整
- 单元测试：多个推荐候选人时摘要格式正确、编号连续
- 单元测试：Markdown 输出符合企业微信格式规范

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：C3.2 企业微信报告推送

## 目标
通过 P3 封装的企业微信 SDK 将筛选报告推送给对应店长。

## 涉及范围
- 创建 `src/c3_push/report_sender.py` — 报告推送服务
  - 根据账号映射找到店长的企业微信 userid
  - 调用 P3 的 channel 接口发送 Markdown 报告
  - 发送失败时记录日志并重试
- 修改 `src/c3_push/__init__.py` — 导出公共接口
- 创建 `tests/test_report_sender.py`

## 前置依赖
- P3（企业微信消息发送 SDK）
- C3.1（报告内容生成）
- P2（账号映射——店长 userid 查询）

## 风险点
- 企业微信 access_token 过期需要自动刷新
- 消息发送频率限制（企业微信 API 限流）

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：正确调用企业微信 API 发送消息（mock HTTP）
- 单元测试：发送失败时重试逻辑正确
- 单元测试：找不到店长 userid 时抛出明确异常

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：C3.3a 筛选链路编排代码 + 单元测试

## 目标
实现指令分发器和筛选链路编排的核心代码，用单元测试验证各组件逻辑。

## 涉及范围
- 创建 `src/common/dispatcher.py` — 指令分发器
  - 接收企业微信回调消息（通过 P6 的 FastAPI 路由传入）
  - 识别店长身份（企业微信 userid → 门店 → Boss 账号）
  - 解析指令类型（"筛选候选人" / "发X" / "分析候选人XXX"）
  - 调度到对应流程
- 创建 `src/common/screening_pipeline.py` — 筛选链路编排
  - 串联 C1 pipeline → C2 pipeline → C3 report_sender
  - 错误处理：任一步骤失败时通知店长并记录日志
  - 操作日志写入 operation_logs 表
  - 并发控制：同一 Boss 账号不应同时运行两个 Playwright session
- 创建 `tests/test_dispatcher.py`
- 创建 `tests/test_screening_pipeline.py`（单元测试，mock 各子模块）

## 前置依赖
- P6（FastAPI app + 异步任务调度——dispatcher 需要挂载到 Web 路由）
- C1.4（C1 流程入口）
- C2.4（C2 流程入口）
- C3.2（报告推送）

## 风险点
- 完整链路执行时间可能较长（Playwright 启动 + 页面加载 + LLM 调用），必须异步执行
- 并发控制：同一 Boss 账号不应同时运行两个 Playwright session

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：指令解析覆盖各种格式（"筛选候选人"、"发1、3"、"分析候选人张三"）
- 单元测试：screening_pipeline 各步骤按序调用（mock 验证）
- 单元测试：某步骤失败时错误通知逻辑正确

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：C3.3b 筛选链路全链路集成测试

## 目标
端到端验证"企业微信指令 → C1 → C2 → C3 推送"的完整链路。

## 涉及范围
- 创建 `tests/integration/test_screening_pipeline.py` — 全链路集成测试
  - mock Playwright 页面 + mock DeepSeek API + mock 企业微信 API
  - 验证完整流程：指令接收 → 简历获取 → 打分 → 报告推送
  - 验证去重：同一候选人不重复打分不重复推送
  - 验证异常：C1 失败时店长收到错误通知
- 补充 `tests/integration/fixtures/` 中的 mock 数据

## 前置依赖
- C3.3a（链路编排代码已完成）

## 风险点
- 集成测试需要同时 mock 三层外部依赖（Boss 直聘 + DeepSeek + 企业微信），fixture 维护成本较高
- 集成测试运行时间较长

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 集成测试覆盖：正常全链路、去重、C1 失败降级、C2 LLM 异常降级

## 回退方式
回退到本任务开始前的 commit

---

## C4：首轮接触自动化

---

# 任务卡：C4.1 店长回复指令解析

## 目标
解析店长在企业微信中回复的打招呼指令，提取目标候选人编号。

## 涉及范围
- 创建 `src/c4_contact/command_parser.py` — 指令解析器
  - 支持格式："发1、3"、"发1,3"、"发 1 3"、"全发"
  - 编号映射到本次筛选报告中的候选人（从最近一次筛选结果查询）
  - 输入校验：编号超范围、非推荐候选人等异常处理
- 修改 `src/common/dispatcher.py` — 添加打招呼指令路由
- 创建 `tests/test_command_parser.py`

## 前置依赖
- C3.1（报告生成——候选人编号格式约定，知道"发1、3"中的编号对应什么）

## 风险点
- 店长输入格式多变（中文逗号/英文逗号/空格/顿号），需要宽松解析
- 需要关联到"最近一次筛选报告"的候选人列表，需要状态管理

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：各种格式的指令正确解析出候选人编号列表
- 单元测试："全发"返回所有推荐候选人
- 单元测试：非法编号返回明确错误信息

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：C4.2 Playwright 打招呼自动化

## 目标
用 Playwright 在 Boss 直聘上对指定候选人执行打招呼操作。

## 涉及范围
- 创建 `src/c4_contact/greeting_sender.py` — 打招呼执行器
  - 主路径：导航到候选人详情页 URL → 点击"打招呼"按钮 → 输入岗位模板消息（≤150 字）→ 发送
  - 降级路径：详情页 URL 失效时，导航到推荐列表页滚动查找
  - 操作间隔：随机延迟（降低检测风险）
  - 结果判断：发送成功/配额耗尽/页面异常
- 创建 `tests/test_greeting_sender.py`

## 前置依赖
- C1.1（Playwright 浏览器上下文管理）
- C1.3（候选人详情页 URL 记录）
- P4a（岗位画像 YAML 中的打招呼模板消息）

## 风险点
- "打招呼"按钮的 DOM 选择器可能因 Boss 直聘改版失效
- 配额耗尽时 Boss 直聘弹出付费弹窗而非提示配额不足，需要检测
- 操作频率过高可能触发反自动化检测

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：mock 页面上正确执行点击+输入+发送流程
- 单元测试：检测到付费弹窗时识别为配额耗尽
- 单元测试：详情页 URL 失效时正确降级到列表页查找

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：C4.3 配额管理 + 执行结果通知

## 目标
记录每个 Boss 账号的每日打招呼消耗，执行完成后将结果推送给店长。

## 涉及范围
- 创建 `src/c4_contact/quota_manager.py` — 配额管理器
  - 每日上限 50 次（畅聊版），当日清零
  - 执行前检查剩余配额，不足时拒绝并提示
  - 每次执行后更新消耗记录（operation_logs 表）
- 创建 `src/c4_contact/pipeline.py` — C4 流程编排
  - 接收解析后的候选人列表 → 检查配额 → 逐个执行打招呼 → 汇总结果
  - 结果推送给店长（企业微信消息：成功 N 个 / 失败 N 个 / 配额剩余）
- 创建 `tests/test_quota_manager.py`
- 创建 `tests/integration/test_c4_pipeline.py`

## 前置依赖
- C4.1（指令解析）
- C4.2（打招呼执行器）
- P3（企业微信消息推送——结果通知）

## 风险点
- 系统记录的配额与 Boss 直聘实际配额可能不同步（其他渠道消耗）
- 批量打招呼时部分成功部分失败的事务性处理

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：配额充足时允许执行
- 单元测试：配额不足时拒绝并返回提示
- 单元测试：跨日配额自动重置
- 集成测试：批量执行结果正确汇总并推送

## 回退方式
回退到本任务开始前的 commit

---

## E2：沟通信息汇总分析

---

# 任务卡：E2.1 聊天记录抓取

## 目标
通过 Playwright 从 Boss 直聘沟通 Tab 获取指定候选人的聊天记录。

## 涉及范围
- 创建 `src/e2_summary/chat_scraper.py` — 聊天记录抓取器
  - 导航到沟通 Tab（/web/chat/index）
  - 优先尝试 `/wapi/zpitem/web/chat/message/list/box` 接口获取消息列表
  - 接口不返回完整内容则 DOM 解析兜底
  - 输出：结构化聊天记录（时间、发送方、内容）
- 创建 `tests/test_chat_scraper.py`
- 创建 `tests/fixtures/wapi_chat_response.json`

## 前置依赖
- C1.1（Playwright 浏览器上下文管理）
- P2（candidates 表——关联候选人信息）

## 风险点
- 聊天记录可能需要滚动加载历史消息
- 候选人定位：需要从沟通列表中找到目标候选人的对话（搜索或滚动）
- 聊天消息可能包含图片/表情等非文本内容

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：正确解析 /wapi/ 聊天接口返回的 JSON
- 单元测试：DOM 兜底解析能提取对话内容
- 单元测试：非文本消息（图片/表情）标记为占位符而非崩溃

## 回退方式
回退到本任务开始前的 commit

---

# 任务卡：E2.2 LLM 沟通汇总生成 + 推送

## 目标
将聊天记录 + 候选人简历数据送入 LLM 生成结构化沟通汇总，推送给店长。

## 涉及范围
- 创建 `src/e2_summary/summary_generator.py` — 汇总生成器
  - 输入：聊天记录 + C2 已有的简历数据和评分
  - LLM prompt：提取关键信息、风险点、亮点、是否建议约面试
  - 输出：结构化汇总文本
- 创建 `src/e2_summary/pipeline.py` — E2 流程编排
  - 接收店长指令（"分析候选人张三"）→ 匹配候选人 → 抓取聊天 → 生成汇总 → 推送
- 修改 `src/common/dispatcher.py` — 添加沟通汇总指令路由
- 创建 `tests/test_summary_generator.py`
- 创建 `tests/integration/test_e2_pipeline.py`

## 前置依赖
- E2.1（聊天记录抓取）
- C2.2（LLM 客户端复用）
- P3（企业微信推送——汇总结果通知）

## 风险点
- "分析候选人张三"指令需要模糊匹配候选人姓名（脱敏姓名只有部分字符）
- 聊天记录长度可能超过 LLM 上下文窗口，需要截断策略
- E2 优先级最低，时间不够可砍

## 验证方式
- make lint 通过
- make test 通过
- make typecheck 通过
- 单元测试：候选人名称模糊匹配逻辑正确
- 单元测试：LLM 汇总输出包含完整结构（关键信息 + 风险 + 亮点 + 约面建议）
- 集成测试：端到端流程 mock 执行成功

## 回退方式
回退到本任务开始前的 commit

---

## 任务总表

| 编号 | 任务名 | 预估文件数 | 前置依赖 | 可并行 |
|------|--------|-----------|---------|--------|
| P1 | Common 基础模块 | 4 | 无 | ✅ 第一批 |
| P4a | 岗位画像文档→YAML 配置 | 12+ | 无 | ✅ 第一批 |
| P2 | 数据库 Schema + 账号映射 | 7 | P1 | 第二批 |
| P3 | 企业微信应用消息接入 | 4 | P1 | ✅ 第二批（与 P2 并行） |
| P4b | 岗位画像配置加载器 | 2 | P4a, P1 | ✅ 第二批（与 P2 并行） |
| P6 | Web 服务入口 | 4 | P1, P3 | 第三批（与 C1 并行） |
| C1.1 | Playwright 浏览器上下文管理 | 3 | P1, P2 | 第三批 |
| C1.2 | 推荐列表 /wapi/ 拦截 + 解析 | 4 | C1.1 | 串行 |
| C1.3 | 候选人详情提取 + 去重入库 | 5 | C1.2, P2 | 串行 |
| C1.4 | C1 集成测试 | 3 | C1.1-C1.3 | 串行 |
| C2.1 | 硬规则引擎 | 3 | P4b, P2 | 第四批 |
| C2.2 | DeepSeek V3 LLM 评估层 | 3 | P1, P4b | ✅ 与 C2.1 可并行 |
| C2.3 | 评分合并 + 判断快照存储 | 4 | C2.1, C2.2, P2 | 串行 |
| C2.4 | C2 集成测试 | 3 | C2.1-C2.3 | 串行 |
| C3.1 | 筛选报告内容生成 | 2 | C2.3 接口约定 | ✅ 可与 C2 并行 |
| C3.2 | 企业微信报告推送 | 3 | P3, C3.1, P2 | 串行 |
| C3.3a | 筛选链路编排代码 | 4 | P6, C1.4, C2.4, C3.2 | 串行 |
| C3.3b | 筛选链路全链路集成测试 | 2 | C3.3a | 串行 |
| C4.1 | 店长回复指令解析 | 3 | C3.1 | ✅ 可与 C3.2 并行 |
| C4.2 | Playwright 打招呼自动化 | 2 | C1.1, C1.3, P4a | ✅ 可与 C4.1 并行 |
| C4.3 | 配额管理 + 执行结果通知 | 4 | C4.1, C4.2, P3 | 串行 |
| E2.1 | 聊天记录抓取 | 3 | C1.1, P2 | 第七批 |
| E2.2 | LLM 沟通汇总 + 推送 | 4 | E2.1, C2.2, P3 | 串行 |

**总计：23 个任务卡**（原 P5 合并入 P2；P4 拆为 P4a+P4b；C3.3 拆为 C3.3a+C3.3b；新增 P6）
