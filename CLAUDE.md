# CLAUDE.md — 笼中仙 AI 招聘助手

## 项目目标

给笼中仙门店店长用的 Boss 直聘线上初筛助手。系统自动获取候选人简历、按岗位画像匹配打分（推荐沟通 / 可以看看 / 不建议）、通过企业微信推送筛选报告，店长确认后对高匹配候选人自动发起首轮接触。V1 目标：AI 推荐准确率 ≥80%、店长筛简历时间减少 70%。

## 技术栈

| 层 | 选型 |
|---|------|
| 浏览器自动化 | Playwright（storageState 多账号隔离） |
| 后端语言 | Python |
| 数据存储 | PostgreSQL |
| LLM | DeepSeek V3（中文、低价、数据不训练） |
| 推送通道 | 企业微信应用消息 |
| 部署 | V1 单台 Linux 服务器（WSL 开发） |

## 目录结构

```
src/
  c1_scraper/        # Boss直聘简历获取（Playwright）
  c2_scorer/         # AI匹配打分（硬规则 + LLM）
  c3_push/           # 企业微信筛选报告推送
  c4_contact/        # 首轮接触自动化
  e2_summary/        # 沟通信息汇总分析
  common/            # 共享模块（DB、配置、日志）
config/
  job_profiles/      # 岗位画像 YAML 配置（每岗位一个文件，含硬规则阈值 + LLM prompt 模板）
storage_states/      # Playwright Cookie 文件（不提交）
tests/
docs/                # 需求文档、架构决策、调研（只读）
```

## 构建与验证命令

```bash
make lint        # ruff 代码检查
make test        # pytest 单元测试 + 集成测试
make typecheck   # mypy 类型检查
```

每次代码变更后必须跑这三个命令，全部通过才算完成。

## 工作方式

- 非小改动（超过 20 行或跨文件）先进 Plan 模式对齐方案，再执行
- 每次只处理一个任务，完成并验证后再开始下一个
- 修改代码后立即运行 `make lint && make test && make typecheck`
- 提交前用 `git diff` 确认没有无关改动
- 开始任务前先阅读 `lessons.md`，避免重复已知错误
- 犯错被纠正后，立即在 `lessons.md` 追加一行记录

## 命名规范

- 函数和变量：`snake_case`
- 类名：`PascalCase`
- 配置文件中的 key：`snake_case`
- 文件名：`snake_case.py`

## 权限边界

- `docs/` 目录只读，不修改、不删除、不新增
- `storage_states/` 已在 .gitignore 中，任何情况不提交
- `.env.local` / `.env.production` 不读取、不修改、不创建
- 数据库 migration 文件生成后必须人工确认再执行

## 禁止事项

- 不要在代码中写死密钥、token、密码（全部走环境变量）
- 不要删除或跳过已有测试
- 不要顺手修改当前任务无关的文件
- 不要修改 `docs/` 下的任何文档
- 不要在没有店长确认的情况下执行打招呼等业务状态变更操作
