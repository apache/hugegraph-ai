# Ontogeny 架构与使用文档

> Ontogeny · Self-improving operational ontology · an ontology that grows
>
> *Ontogeny*（个体发育）—— 希腊语 **onto-**（存在，即 *ontology* 本体论的词根）+ **genesis**（诞生、发育）：生物学术语，指一个个体从胚胎到成体的**全生命周期发育**。这个名字就是产品主张：本体不是静态的 schema，而是一个活物——在 Git 里被定义，编译成表与图，再在使用中成长。

**中文** | [English](../en/README.md)


把企业的**名词**（对象·属性·链接）与**动词**（动作·函数·权限）建模成 Git 里的声明式 YAML，编译为强类型对象表与统一 API，供应用、分析与 AI Agent 共用；写路径经「规则 → Cedar 策略 → 事务 → 不可变审计」五段式，副作用走事务性 outbox；并以 **RSI 自进化闭环**在治理轨道内递归改进模型本身（LLM 出变异 · 确定性评测做选择 · T0–T3 分层晋升）。

文档分两部分：**第一部分·架构文档**基于当前代码实态讲清四带总览、11 种 DSL 资源、数据与派生链路、函数生态、Agent 治理与自进化闭环；**第二部分·使用文档**以真实运行的界面截图带您完成启动、建模、函数编辑与治理巡检（参考手册含 API 核心端点、CLI 与环境变量；全量契约以 `/openapi.json` 为准）。

| 指标 | 值 |
|---|---|
| DSL 资源 | 11 种 |
| API 操作 | 79 个 |
| 前端路由 | 15 页 + 9 条兼容重定向 |
| 动作效果 | 7 类 |
| outbox 消费者 | 4 路 |
| 策略 | Cedar 子集 |
| 图引擎 | Apache HugeGraph |
| 真源 | Git 声明式 YAML |
| LLM | Ollama（可换） |
| 测试 | 456 后端 · 241 前端 · 8 E2E |

## 第一部分 · 架构文档（PART I · ARCHITECTURE）

六章讲清系统的真实构造：从四带总览到本体 DSL、数据链路、动力学层、Agent 治理，再到自进化 RSI 闭环；最后以「边界与质量」收束——明确不做什么，以及测试如何映射到承诺。

| # | 文档 | 内容 |
|---|---|---|
| 01 | [总览架构图](architecture/01-overall-architecture.md) | 四带总览：一等公民 · 离线闭环 · 在线主链路 · 支撑层 · 贯穿机制；第三方组件位与降级 |
| 02 | [本体模型与 DSL](architecture/02-ontology-model-and-dsl.md) | 11 种资源、两种派生、mini-expr 表达式语言、校验器与 lint |
| 03 | [数据与派生链路](architecture/03-data-and-derivation.md) | 属性级所有权、同步三策略 + 四铁律、outbox 四消费者、派生 Worker、图投影 |
| 04 | [动力学层：动作与函数](architecture/04-actions-and-functions.md) | 函数生态四能力、函数型动作与效果计划 |
| 05 | [Agent 治理子系统](architecture/05-agent-governance.md) | 插件/会话/审批/预算、三扇门、引擎范式与第三方接入 |
| 06 | [自进化 RSI](architecture/06-rsi-self-evolution.md) | 六拍循环、8 种信号检测器、T0–T3 分层晋升、字段自动建模实例 |
| 07 | [边界与质量](architecture/07-boundaries-and-quality.md) | 明确不做、已知边界、测试地图 |

## 第二部分 · 使用文档（PART II · USAGE）

以下章节带您实际操作：一条命令启动、逐页认识界面、在函数编辑器里写并验证第一段沙箱代码。全部截图取自真实运行的演示实例（`ontogeny serve --demo`，product-manufacturing 样例域），所见即所得。

| # | 文档 | 内容 |
|---|---|---|
| 08 | [快速开始](usage/08-quickstart.md) | 一条命令启动、首次登录 |
| 09 | [界面导览](usage/09-ui-tour.md) | 六个高频页面截图导览 |
| 10 | [函数编辑器实战](usage/10-function-editor.md) | 试运行 / 保存并发布 / 空函数引导 |
| 11 | [案例流程](usage/11-manufacturing-case.md) | 离散制造运营闭环 16 步全链路 |
| 12 | [参考手册](usage/12-reference.md) | CLI · 环境变量 · API 核心端点 · 前端路由 · 错误码 |

---

源文件索引：DSL `server/ontogeny/core/{models,loader,validator,linter,expr,types}.py` · 注册表 `server/ontogeny/registry/{compiled,store}.py` · 数据 `server/ontogeny/stores/{ddl,repo,sync,sources}.py` · 动力学 `server/ontogeny/action/{runtime,outbox,models}.py` · 策略 `server/ontogeny/policy/engine.py` · 读路径 `server/ontogeny/engine/service.py` · 函数 `server/ontogeny/functions/{sandbox,child,derivation}.py` · Agent `server/ontogeny/agent/{broker,catalog,models}.py` · `mcp_server.py` · 进化 `server/ontogeny/evolve/{diagnoser,proposer,evalrunner,promoter}.py` · 遥测 `server/ontogeny/telemetry/service.py` · 投影 `server/ontogeny/projection/{compiler,hugegraph}.py` · LLM `server/ontogeny/llm/ollama.py` · 服务组合 `server/ontogeny/service.py` · `api/app.py` · `cli.py`。
