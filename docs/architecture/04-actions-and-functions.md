# 04 · 动力学层：动作与函数生态（KINETIC · action/ · functions/ · policy/）

> 所属：[架构文档](../README.md#第一部分--架构文档part-i--architecture)

**中文** | [English](../en/architecture/04-actions-and-functions.md)


**Action 改世界、Function 算答案**——Palantir Ontology 同为动力学层一等公民，Ontogeny 忠实继承，并把函数生态补齐到四项能力（LLM 注册 · 派生底层 · 发布 API · 流式规划中）。

## 4.1 函数生态四能力

### llm · 函数内调大模型（预算限次 · 子进程零网络）

| | |
|---|---|
| 声明 | `capabilities: [{llm: {model, max-calls}}]` |
| 调用 | `ontogeny.llm(prompt, system=…)` → stdio RPC → 平台网关（可换 provider） |
| 守卫 | 未声明 → 边界拒绝；超预算 → `SandboxError`；未配置 → 指向 ONTOGENY_LLM_BASE_URL |

### derived · 派生属性底层（物化 · 跨对象 · triggers）

| | |
|---|---|
| 声明 | 属性 `derived: {kind: function, entry, object_param, triggers}` |
| 执行 | 派生 Worker outbox 消费 → 整批一次子进程 → 单事务落列 |
| 示例 | `equipment.open_mo_count` 跨对象统计未关闭维修单 |

### publish · 发布 Function API（版本锚定 · 漂移即 409）

| | |
|---|---|
| 声明 | `publish: {enabled: true}` |
| 版本 | 函数源码 sha256 前 12 位；`GET /functions/{n}/versions` |
| 锚定 | invoke 带 `version`：不匹配 → 409（感知逻辑漂移，而非静默变更） |

### stream · 流式调用（设计中）

| | |
|---|---|
| 形态 | 声明 llm 能力的函数开放 SSE 逐 token 输出 |
| 边界 | 流式数据管道不属于平台范围 |

**沙箱边界（全能力共用）**：独立子进程 + rlimits + 墙钟超时杀进程 + PYTHONDONTWRITEBYTECODE；跨界 RPC 由父进程按 capabilities 裁决；返回对象与 API 同形（**修复过沙箱内派生属性不可见导致库存全算 0 的错算**）。

## 4.2 函数型动作：效果计划（Function 出主意，Action 落地）

```yaml
# actions/raise-maintenance-order.yaml（节选）
spec:
  target: maintenance-order
  execution: { kind: function, entry: maintenance_plan.py:plan_maintenance_order }
  rules: [ { expr: "parameters.symptom != ''", message: 故障现象必填 } ]
  policy: maintenance-policies
# 函数在沙箱内从设备档案反查厂区（授权属性绝不能由客户端传入），返回效果计划：
```

```json
[{ "kind": "create-object", "properties": {
     "mo_id": {"$expr": "newId('MO')"},       // $expr = 引擎求值
     "equipment_id": "EQ-01",                  // 其余 = 数据
     "site": "north", "status": "OPEN",
     "opened_at": {"$expr": "now()"} }}]
// 引擎在同一事务内原子执行——事务/审计/策略始终留在引擎。
```

**为什么区分表达式与数据**：声明式效果的值是表达式（静态可校验），函数计划携带的是运行时数据——不区分时 `"EQ-01"` 会被解析成 `EQ - 01`。
