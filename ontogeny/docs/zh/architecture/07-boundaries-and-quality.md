# 07 · 边界与质量（NON-GOALS · LIMITS · TEST MAP）

> 所属：[架构文档](../README.md#第一部分--架构文档part-i--architecture)

**中文** | [English](../../en/architecture/07-boundaries-and-quality.md)


## 明确不做

批/流计算网格 · DAG 编排（Airflow 已赢）· CDC 采集（只消费 Debezium）· 图内核与算法库（HugeGraph 承担）· 第四个语义标准（OWL / RDF 承担）· 无界 RSI · AI 权限后门

## 已知边界

OWL/RDF 导入未实现（导出在 M4）· changelog 依赖 Kafka 源 · 审批运行时（DSL 已声明）· 图算法任务 · 多租户与删列/改类型迁移 · TS 沙箱（deno sidecar 规划）· 流式调用设计中

## 测试地图（后端 456 项 · 前端 241 项 · E2E 8 项）

| 层 | 用例 | 覆盖要点 |
|---|---|---|
| `test_core` + `test_expr` | 41 | DSL 模型/loader/校验（黄金本体 + 12 类注入错误）/mini-expr 语义、precedence、时间语义 |
| `test_registry` + `test_restart` | 16 | 发布/重建/软删/血缘；**重启不丢策略文本**、函数源可定位、缺包目录响亮报错 |
| `test_stores` + `test_schema_evolution` | 18 | 同步三策略/所有权/隔离区/水位；跨包 DDL 无冲突；**T0 新增属性自动补列可查**；时区保真 |
| `test_action` | 15 | 五段式/规则/策略/掩码/幂等/409/outbox 白名单/SSE |
| `test_engine_functions` + `test_graph_explore` + `test_function_ecosystem` | 27 | 装配/派生可见/**DFS 回溯双回归**/沙箱能力与超时/**LLM 预算**/版本锚定/跨对象触发 |
| `test_agent` + `test_agent_approval` + `test_agent_engine` + `test_agent_eval` | 35 | 插件身份/会话预算/工具目录/审批门/**builtin-llm 引擎循环**/Agent-eval |
| `test_evolve` + `test_demo` + `test_demo_story` + `test_llm` + `test_domain_import` + `test_product_manufacturing` + `test_projection*` | 81 | RSI 全环（预算与宪法拦截）/演示引导与故事/Ollama（含 live 2 项可跳过）/域包导入/产品制造域契约/投影 |
| `test_api` + `test_cli` + `test_deploy` | 28 | HTTP 壳 e2e/CLI/CMD 标志与路由存在性/构建上下文一致性 |
| `test_system_example` | 27 | 系统级示例全链路（含 **示例目录树哈希守护**：测试污染示例即失败） |

**E2E**（vitest + globalSetup）：真实 Python 后端子进程 + 真实 Ollama，8 项覆盖 meta/sync/查询掩码/动作全周期/追溯/RSI 闭环/助手两链路（集群不可达自动跳过）。
