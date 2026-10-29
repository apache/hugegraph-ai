# 12 · 参考手册（CLI · ENV · API · ROUTES · ERRORS）

> 所属：[使用文档](../README.md#第二部分--使用文档part-ii--usage)

**中文** | [English](../../en/usage/12-reference.md)


## 12.2 CLI（ontogeny）

| 命令 | 作用 |
|---|---|
| `validate <pkg>` · `lint <pkg>` · `docs <pkg>` | 包校验 / 规范检查 / 生成文档 |
| `diff <old-pkg> <new-pkg>` | 比较两个包的语义差异 |
| `publish <pkg>` | 校验、持久化并编译数据库快照；`--db` 应与服务一致 |
| `sync <type>` | 按该类型配置的策略同步一次（原子；重复执行需外部调度器） |
| `serve [--demo] [--copy-package] [--reseed] [--data-dir DIR]` | 起服务（--demo 全自包含；--open 自动开浏览器；--no-build-ui 跳过构建） |
| `evolve signals \| promote <id>` | 聚合适应度信号 / 按策略晋升提案 |
| `projection rebuild` | 重建图投影（删空间 → schema → Loader 回填） |


CLI 数据库命令使用 `ONTOGENY_DB_DSN` 或 `--db`，不会根据运行中演示服务的 `--data-dir` 自动选择数据库。例如，默认源码演示应传 `--db sqlite+aiosqlite:///$PWD/.ontogeny-demo/ontogeny.db`。CLI 发布不会通知另一个已运行进程重新加载；请重启该进程或通过其管理员 API 发布。当前没有 `sdk generate` 命令。

## 12.3 环境变量

### 核心运行时

| 变量 | 默认 | 用途 |
|---|---|---|
| `ONTOGENY_DB_DSN` | `sqlite+aiosqlite:///./ontogeny.db` | 元数据 + 对象表 + outbox；`--demo` 在未显式覆盖时提供自己的 SQLite DSN。Postgres 需安装 `postgres` extra |
| `ONTOGENY_DATA_DIR` | 演示数据目录；否则为 SQLite 数据库目录或 `.ontogeny/` | 仅所有者可访问的 `admin-bootstrap-password` 文件目录；不会覆盖已有文件 |
| `ONTOGENY_ADMIN_USER` | `admin` | 管理员初始用户名 |
| `ONTOGENY_ADMIN_PASSWORD` | 未设置 | 显式指定管理员初始密码；不创建凭据文件，不会重置已有管理员密码 |
| `ONTOGENY_PACKAGE_ROOT` | — | 本体包 Git 工作副本；DB 重建快照时函数源码靠它定位 |
| `ONTOGENY_UI_DIR` | `web/dist` | 同源托管的前端构建产物（容器内置） |
| `ONTOGENY_WEBHOOK_ALLOWLIST` | 空 = 全拒 | 出站 webhook 域名白名单（防 SSRF） |
| `ONTOGENY_DEV_AUTH` | `0` | 仅在开发时设为 `1`，以接受 X-Ontogeny-Principal 头。 |
| `ONTOGENY_LLM_BASE_URL / ONTOGENY_LLM_MODEL` | 未配置 | Ollama 端点与模型；未配置时依赖 LLM 的助手、引擎及函数调用不可用 |
| DSL 内 `${ERP_DSN}` 等 | — | 业务配置由部署注入；webhook 变量缺失只影响投递不影响事务 |

## 12.4 API 核心端点（按域分组 · 全量与实时契约以 `/openapi.json` 为准；以下端点均需加 `/api/v1` 前缀）

| 域 | 端点 | 方法 | 说明 |
|---|---|---|---|
| **meta** | `/meta/ontology` | GET | 编译快照导出（SDK/MCP/前端元数据源） |
| **meta** | `/meta/lineage` | GET | 血缘 DAG |
| **objects** | `/objects/{t}/query` | POST | filter/sort/分页/聚合/link 展开；返回命中数与耗时 |
| **objects** | `/objects/{t}/{id}` · `/history` | GET | 单对象（掩码后）· 版本历史 |
| **objects** | `/objects/{t}/{id}/links/{l}` | GET | 关系导航 |
| **objects** | `/objects/{t}/aggregate` | POST | count/sum/avg/min/max |
| **objects** | `/data/preview` | GET | 数据预览 |
| **actions** | `/actions/{a}/validate` | POST | 干跑：规则逐条 + 策略裁决，零写入 |
| **actions** | `/actions/{a}/execute` | POST | 唯一写入口（expected_revision / idempotency_key） |
| **functions** | `/functions/{f}/invoke` | POST | 沙箱调用；可带 `version` 锚定（漂移 409） |
| **functions** | `/functions/{f}/versions` | GET | 当前内容版本 |
| **graph** | `/graph/explore` | POST | **邻域探索**：随机/指定起点 + N 节点，深度优先，双向不重复，seed 可复现 |
| **graph** | `/graph/traverse` | POST | 显式路径逐跳遍历 |
| **graph** | `/graph/projection[/vertices\|edges]` | GET | 可选的 HugeGraph 投影读取 |
| **graph** | `/graph/algorithm` | POST | 尚未实现；所有配置下均返回 501 |
| **agent** | `/agent/plugins` | GET | 插件目录 |
| **agent** | `/agent/sessions…` | POST/GET | 会话开/列/详情/finish |
| **agent** | `/agent/sessions/{id}/tools/{tool}` | POST | 单门执行（读直执行 / 写挂审批） |
| **agent** | `/agent/sessions/{id}/run` | POST | 按 engine.kind 分发驱动循环（builtin-llm / external-pull） |
| **agent** | `/agent/approvals…` | GET/POST | 审批队列与决策 |

其余组：**audit**（/audit/revisions）· **evolve**（/evolve/signals · aggregate · diagnose · proposals[/eval|promote]）· **assistant**（/assistant/chat，grounding + propose 模式）· **admin**（llm/status · publish · sync/{t} · outbox/dispatch · derive · projection/rebuild · **domains[/import]（zip 本体包导入）**）· **subscriptions**（SSE）。完整清单以 `/docs`（OpenAPI）为准。

正常 `serve`/ASGI factory 会约每秒处理一次 outbox 并 drain 派生任务；这不等于定时拉取源库。`sync.schedule` 只是声明，周期性源同步需外部调度器调用 CLI 或管理员同步端点。仍可手动调用 `/api/v1/admin/outbox/dispatch`，它与后台循环共用进程内锁。

## 12.5 前端路由

| 路由 | 页面 |
|---|---|
| `/` | 运行看板：Ontogeny 介绍 + 架构总览 · 本体模型 · 智能 Agent · RSI 闭环，四大区块 |
| `/ontology` · `/ontology/:t` | 本体浏览器（卡片画布 · 悬停高亮引用）· 类型详情 |
| `/knowledge` · `/objects/:t[/:id]` | Knowledge：语义层编辑 + 对象数据 / 链接 / 投影标签（旧 /data · /objects 重定向至此）· 对象浏览器 / 对象详情（版本时间线 + 链接导航） |
| `/action` · `/actions/:n` · `/functions/:n` | 动力学层编辑（动作 · 函数 · 策略集）· Action 运行器（schema 表单 + dry-run + 结构化错误）· 函数测试台 |
| `/graph` | 图探索：邻域探索（DFS）· 路径遍历 · 投影视图 |
| `/agent/manage` · `/evolve[/…]` | **Agent 会话管理**（会话 / 审批 / 插件；旧 /agent/* 重定向）· 自进化控制台 + 提案详情（diff / 评测 / 晋升） |
| `/audit` · `/admin` · `/access` | 审计流 · 运维与扩展（LLM 网关 / 注册表 / 投影 / 演示环境）· 权限与角色 |

全局：⌘K 搜索 · 中英切换（持久化 + `<html lang>`）· 浅/深主题 · **身份模拟（需 `ONTOGENY_DEV_AUTH=1`）**（同一页面随身份看到掩码或明文、越权即 403——策略面在 UI 上可见）。

## 12.6 错误码（前端有本地化解释）

| code | HTTP | 含义 |
|---|---|---|
| `RULE_REJECTED` | 422 | 业务规则拒绝（修订已入库；附命中规则与修订号） |
| `POLICY_DENIED` | 403 | Cedar 策略拒绝（默认拒绝语义；拒绝留痕） |
| `REVISION_CONFLICT` | 409 | 乐观锁冲突 / 幂等键归属冲突 / 函数版本漂移 |
| `CONSTITUTION_VIOLATION` | 403 | 提案触碰宪法面 → 降 T3 人审 |
| `BUDGET_EXCEEDED` | 429 | T0 周预算耗尽 / Agent 会话预算超限 |
| `CAPABILITY_DENIED` / `SANDBOX_ERROR` | 403/500 | 沙箱能力越权 / 沙箱执行失败 |

## 12.7 函数执行与评测边界

函数源码读、写及试运行接口需要管理员权限。Python 函数执行可信包内代码，资源限制并非操作系统隔离。编辑器试运行不会保存编辑后的源码、发布版本或新增源码修订，但可能调用外部 LLM/HTTP 服务，任意 Python 代码也可能产生其他副作用。

Agent EvalSuite 脚本使用临时 SQLite 数据库及生产对象数据快照。由于可能调用外部服务，这类评测会拒绝函数工具和函数型动作，并返回明确错误；它与管理员函数试运行不同。查询/回放评测及 API 契约以当前实现和 `/openapi.json` 为准。
