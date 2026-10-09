# 12 · 参考手册（CLI · ENV · API · ROUTES · ERRORS）

> 所属：[使用文档](../README.md#第二部分--使用文档part-ii--usage)

**中文** | [English](../en/usage/12-reference.md)


## 12.2 CLI（ontogeny）

| 命令 | 作用 |
|---|---|
| `validate / lint / docs / diff <pkg>` | 包校验（阻断级）/ 规范 / 生成文档 / 语义 diff |
| `publish <pkg>` | 校验 + 持久化 + 编译快照（热路径切快照） |
| `sync <type>` | 单类型增量同步（原子，可被 Airflow 调） |
| `serve [--demo] [--reseed] [--data-dir]` | 起服务（--demo 全自包含；--open 自动开浏览器；--no-build-ui 跳过构建） |
| `evolve signals \| promote <id>` | 聚合适应度信号 / 按策略晋升提案 |
| `projection rebuild` | 重建图投影（删空间 → schema → Loader 回填） |
| `sdk generate` | SDK 生成（规划位） |

## 12.3 环境变量

### 核心运行时

| 变量 | 默认 | 用途 |
|---|---|---|
| `ONTOGENY_DB_DSN` | `sqlite+aiosqlite:///./ontogeny.db` | 元数据 + 对象表 + outbox（生产用 Postgres asyncpg） |
| `ONTOGENY_PACKAGE_ROOT` | — | 本体包 Git 工作副本；DB 重建快照时函数源码靠它定位 |
| `ONTOGENY_UI_DIR` | `web/dist` | 同源托管的前端构建产物（容器内置） |
| `ONTOGENY_WEBHOOK_ALLOWLIST` | 空 = 全拒 | 出站 webhook 域名白名单（防 SSRF） |
| `ONTOGENY_DEV_AUTH` | `1` | 接受 X-Ontogeny-Principal 头（生产关闭，换 OIDC） |
| `ONTOGENY_LLM_BASE_URL / ONTOGENY_LLM_MODEL` | 未配置 | Ollama 端点与模型；未配置 → 助手 503，其余功能不受影响 |
| DSL 内 `${ERP_DSN}` 等 | — | 业务配置由部署注入；webhook 变量缺失只影响投递不影响事务 |

## 12.4 API 核心端点（按域分组 · 全量与实时契约以 `/openapi.json` 为准，共 79 操作/70 路径）

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
| **graph** | `/graph/projection[/vertices\|edges]` · `/graph/algorithm` | GET/POST | 投影读取与图算法（M3） |
| **agent** | `/agent/plugins` | GET | 插件目录 |
| **agent** | `/agent/sessions…` | POST/GET | 会话开/列/详情/finish |
| **agent** | `/agent/sessions/{id}/tools/{tool}` | POST | 单门执行（读直执行 / 写挂审批） |
| **agent** | `/agent/sessions/{id}/run` | POST | 按 engine.kind 分发驱动循环（builtin-llm / external-pull） |
| **agent** | `/agent/approvals…` | GET/POST | 审批队列与决策 |

其余组：**audit**（/audit/revisions）· **evolve**（/evolve/signals · aggregate · diagnose · proposals[/eval|promote]）· **assistant**（/assistant/chat，grounding + propose 模式）· **admin**（llm/status · publish · sync/{t} · outbox/dispatch · derive · projection/rebuild · **domains[/import]（zip 本体包导入）**）· **subscriptions**（SSE）。完整清单以 `/docs`（OpenAPI）为准。

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

全局：⌘K 搜索 · 中英切换（持久化 + `<html lang>`）· 浅/深主题 · **身份切换**（同一页面随身份看到掩码或明文、越权即 403——策略面在 UI 上可见）。

## 12.6 错误码（前端有本地化解释）

| code | HTTP | 含义 |
|---|---|---|
| `RULE_REJECTED` | 422 | 业务规则拒绝（修订已入库；附命中规则与修订号） |
| `POLICY_DENIED` | 403 | Cedar 策略拒绝（默认拒绝语义；拒绝留痕） |
| `REVISION_CONFLICT` | 409 | 乐观锁冲突 / 幂等键归属冲突 / 函数版本漂移 |
| `CONSTITUTION_VIOLATION` | 403 | 提案触碰宪法面 → 降 T3 人审 |
| `BUDGET_EXCEEDED` | 429 | T0 周预算耗尽 / Agent 会话预算超限 |
| `CAPABILITY_DENIED` / `SANDBOX_ERROR` | 403/500 | 沙箱能力越权 / 沙箱执行失败 |
