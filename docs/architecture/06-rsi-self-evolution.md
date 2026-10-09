# 06 · 自进化 RSI：治理内递归（evolve/ · telemetry/ · EvalSuite · EvolutionPolicy）

> 所属：[架构文档](../README.md#第一部分--架构文档part-i--architecture)

**中文** | [English](../en/architecture/06-rsi-self-evolution.md)


递归改进的对象是**模型层**（ontology + action），平台宪法永不被循环触碰。变异外包给 LLM，**选择函数不外包**——这是与无界 RSI 的分界线。
循环没有玄学，每一拍都是确定性代码 + 落库产物：**信号**来自四类检测器对遥测的规则扫描（`ontogeny_evolve_signal`），**变异**只能出自白名单（`ontogeny_evolve_proposal`，必须携带 rationale），**评测**全部确定性可求值（无 LLM-judge），**晋升**走 T0–T3 分层 + ISO 周预算（`ontogeny_evolve_budget`）。任何一拍的产物都是数据库行和 Git diff——可审计、可重放、可回滚。

## RSI 循环 · 六拍（每拍落库、每拍可独立重放）

1. **信号聚合**：`ontogeny evolve signals`（= `POST /evolve/aggregate`）——检测器扫 168h 窗口：空结果率、未建模过滤字段、热点查询、慢查询 P95、动作规则拒绝率、Agent 工具错误、审批拒绝率、隔离区坏行 → 写 `ontogeny_evolve_signal`（8 种检测器全表见下方信号全景）
2. **归因**：`POST /evolve/diagnose`——diagnoser.py 把信号翻译成 gap 假设（附证据计数，marking-aware）；信息性信号只呈现给人/LLM，**不自动变异**
3. **提案**：启发式提议器（零 LLM，缺省路径）或 LLM 提议器（Ollama 结构化 `{mutations, rationale}`）→ 写 `ontogeny_evolve_proposal`；**解析失败或无 rationale 在入口即丢弃**
4. **评测**：`POST /evolve/proposals/{id}/eval`——EvalRunner 在**候选包副本**上跑全部 EvalSuite（线上不动）；report 与 passed 与否都写回提案行
5. **分级晋升**：`ontogeny evolve promote {id}`——promoter 按 EvolutionPolicy 定 tier → 查周预算 → 查宪法 → T0 应用并发布 / T1·T2 出人审分支 / T3 转 `awaiting_human`
6. **生效与回滚**：晋升即 `registry.publish` + `reload()` 热切换编译快照（新 schema 立即在线）；回滚 = `git checkout` 上一版包目录再 publish——**文件系统即版本，Git 即撤销键**

## 三阶段分览

### ①② 观察 → 归因（telemetry/ · diagnoser.py）

| | |
|---|---|
| 信号 | 8 种检测器（见下方**信号全景**表）：查询空结果率 · **未建模过滤字段** · 热点查询 · 慢查询 P95 · 动作规则拒绝率 · Agent 工具错误 · 审批拒绝率 · 隔离区坏行 |
| 触发线 | 按检测器各异：空结果率 ≥10% · 未建模字段 ≥5 次 · 热点 ≥3 次 · P95 ≥2s · 规则拒绝 ≥30%·5 次 · Agent 错误 ≥3 次 · 审批拒绝 ≥30%·5 次（均按 168h 窗口，防噪声） |
| 归因 | 确定性检测器 → gap 假设（附证据计数）；**marking-aware**：被掩码字段的信号不出本体推断 |

### ③ 变异 → DSL diff（proposer.py）

| | |
|---|---|
| 启发式 | 确定性：缺口类型 → 变异（add-optional-property / enum-widen），零 LLM 也能走完全循环 |
| LLM | Ollama 结构化输出 `{mutations, rationale}`，prompt 只允许两种变异形状；**解析失败或无 rationale 一律丢弃**——解释不了的提案进不了评测 |

### ④ 确定性评测（evalrunner.py · EvalSuite）

| | |
|---|---|
| L1 | validate / lint（结构 + 宪法红线，promoter 内执行） |
| **L2** | 查询回归（**按声明 schema 校验列**，空结果不判红）+ **动作时间旅行回放**：历史修订在新规则下反事实执行，与人类真实决策比对 |
| L3/L4 | 影子双跑 · LLM 只解释归类，**永不做通过条件**——LLM 不可复现，所以脚本是受测物 |

## 信号全景 · 8 种检测器（telemetry/service.py 实测实现）

| 信号（kind） | 触发线（168h 窗口） | 大白话 · 它在说什么 | 通道 |
|---|---|---|---|
| `empty_query_rate` 查询空结果率 | ≥10% | 某对象类型 ≥10% 的查询返回 0 行——"大家一直查它但查不到"。可能数据未同步，也可能建模与实际不符。 | 信息性（仅呈现） |
| `unmapped_filter_field` 未建模过滤字段 | 同一字段 ≥5 次 | **最强的进化信号**：过滤字段在源库真实存在但本体未建模（schema 缺口）——直接生成"加可选属性"提案。 | **自动提案**（T0 白名单） |
| `hot_query` 热点查询 | 完全相同的过滤 ≥3 次 | 同一查询被反复执行且**有结果**——高频真实用法。方向不同：不是"哪里坏了"，而是把关键查询**固化为评测用例**（eval-case-synth），让回归考试越来越贴近真实使用。 | 评测资产（用例合成） |
| `slow_query_p95` 慢查询 | P95 ≥2000ms | 某类型查询 P95 延迟超 2 秒——"越查越慢"。提示需要索引、物化列或投影加速；属于性能信号，不改模型。 | 信息性（仅呈现） |
| `action_rule_reject` 动作规则拒绝率 | ≥30% 且样本 ≥5 | 某动作的执行频繁被业务规则拦下——"大家总想干、规则总说不"。规则与现实脱节：规则过严，或流程该改。**规则是人类意图，不会自动改**。 | 信息性（仅呈现） |
| `quarantine_rate` 同步隔离区坏行 | 出现即记录 | 源库送来本体不认识的值——最典型：**枚举扩域**。源库新增 "URGENT" 而本体枚举没有 → 整行进隔离区（TYPE_MISMATCH，不阻塞批次）。若值形似合法枚举成员 → 自动生成"枚举扩宽"提案。 | **自动提案**（T0 白名单） |
| `agent_tool_error` Agent 工具错误 | 同一工具 ≥3 次 | Agent 反复调用某工具但总失败——工具本身或其输入契约有问题。 | 信息性（仅呈现） |
| `approval_reject_rate` 审批拒绝率 | ≥30% 且样本 ≥5 | **治理面信号**：人反复拒绝某个 Agent 插件的写审批——"AI 老提要求、人老说不"。要么插件权限给宽了，要么它该走别的动作。**只呈现给人，绝不自动改策略**。 | 信息性（仅呈现） |

三条设计不变量：① **阈值可调**——每种触发线都可被域自己的 EvolutionPolicy.observability 覆盖（不同域敏感度不同）；② **防重复**——同窗口内相同 (kind + 证据指纹) 只记一条，滚动窗口不会刷屏；③ **信息性 ≠ 可进化**——错误多不代表该改模型，只有**结构性缺口**（缺字段、坏行）进入自动提案通道，其余只呈现给人。

## T0–T3 分层晋升（EvolutionPolicy · evolution.yaml，仅人可改）

| Tier | 白名单变异 | 门槛 | 动作 |
|---|---|---|---|
| **T0 自动合并** | `add-optional-property` · `enum-widen` · `index-tune` | eval 全绿 + 周预算（示例包 **8 次/周**，单命名空间） | validate → 应用变异 → publish → **热切换**，全程无人 |
| **T1 人工 PR** | 白名单外的一切安全变更 | validate | 机器落地已校验分支目录 `pkg.proposal-{id}`（无机械应用器的变异由人在分支内改），人来合、发 |
| **T2 金丝雀** | `rule-change` · `effect-change` · `function-change` | eval 绿 + 影子 diff 干净 + **显式审批** | 同 T1 分支流程；上线后影子双跑对比，无回归才切流 |
| **T3 仅人类** | `policy-loosen` · `marking-change` · `ownership-change` · `eval-passbar-change` · `destructive-migration` | 机器提案触碰即 `ConstitutionViolationError` | 提案转 `awaiting_human`，审计写明原因——**自动化的路径根本不存在**，不是被拦截 |

**Graduation（tier 升级）**：同类别变更连续 10 次干净晋升 + 人工批准才可 T1→T0——且这次升级本身是 T3 操作。T0 预算是按 ISO 周记的数据库行，超限抛 `BudgetExceededError`：**宁可让循环停一拍，也不让它跑快一点**。

## 实际例子：一个字段从"看板报错"到"自动建模"的全过程

场景：车间分析看板持续用 `cost_center`（成本中心）过滤采购订单。该列在源表 `mes.purchase_orders` 里真实存在，但建模时被遗漏——查询 API 对未建模过滤字段抛 `NotFoundError`，看板一直红着。没有人提需求单，循环自己发现了它。

```json
// 第 1 拍 · 信号——ontogeny evolve signals 的检测器 #2（≥5 次触发）
{"id": 17, "kind": "unmapped_filter_field",
 "evidence": {"object_type": "purchase-order", "field": "cost_center", "count": 23}}   // → ontogeny_evolve_signal
```

```json
// 第 2–3 拍 · 归因 + 提案——POST /evolve/diagnose（启发式提议器，零 LLM）
{"id": 42, "gap_kind": "add-optional-property", "origin": "heuristic", "status": "proposed",
 "diff": [{"mutation": "add-optional-property", "object": "purchase-order",
           "prop": "cost_center", "type": "string", "column": "cost_center"}],
 "rationale": "filter field 'cost_center' used 23x on 'purchase-order' but is not modeled; add as optional property"}
// rationale 携带证据计数，无它即丢弃
```

```json
// 第 4 拍 · 评测——POST /evolve/proposals/42/eval（候选包副本上跑，线上不动）
{"passed": true, "suites": {"production-flow-suite": {"passed": true, "cases": [
    {"name": "open-sales-orders", "kind": "query", "ok": true, "latency_ms": 2.4, "rows": 17},
    {"name": "released-production-orders", "kind": "query", "ok": true, "latency_ms": 3.1, "rows": 8},
    {"kind": "replay", "action": "report-operation", "ok": true,
     "replays": 214, "outcome_matches": 214},                 // 累加语义，不设 no-double-close
    {"kind": "replay", "action": "close-maintenance-order", "ok": true,
     "replays": 57, "outcome_matches": 57, "after_state_rejections": 57}]},   // 57 条"已关闭再关闭"全被候选规则拒
  "quality-suite": {"passed": true, "cases": "… 3 cases green …"}}}
// 查询回归按"声明 schema"比对列名：cost_center 现在是合法过滤字段；空结果不判红（过滤无命中是合法业务状态）
// 回放 = 时间旅行：90 天历史修订在候选规则下反事实重放，新包没有重写历史、也没有放宽安全语义
```

```json
// 第 5–6 拍 · 晋升 + 生效——ontogeny evolve promote 42
{"status": "promoted", "tier": "t0-auto-merge",
 "budget_used": 4, "budget_cap": 8,                      // 本周第 4 次 T0，用满即 BudgetExceededError
 "content_hash": "b7f3c9…", "revert": "ontogeny publish pkg  # republish 上一 git 版本"}
```

```diff
// 循环写下的唯一 diff——purchase-order.yaml（git diff 一眼可审）
   properties:
     created_at:
       type: timestamp
       display: 创建时间
+      cost_center:
+        type: string
+        display: cost_center
+        required: false
   backing:
+    mapping:
+      cost_center: cost_center   # 指向源表 mes.purchase_orders 同名列
// publish + reload() 热切换后，看板的下一次查询即命中——从信号到生效，无人参与
```

**治理边界在同一例子里同样具体**：若 LLM 提议器拿同一条信号提议"顺手把 `approve-purchase-order` 的金额上限规则放宽"（`rule-change` ∉ T0 白名单），分类器直接给 T2——落地人审分支 + 影子双跑，绝不因"顺手"自动生效；若提案触及 T3 面（例如放宽 Cedar 方向），promoter 当场抛 `ConstitutionViolationError`，提案转 `awaiting_human`。另有一条同构路径：源 ERP 新出现的枚举值（如 `status=CLOSED`）会先被同步挡进隔离区（TYPE_MISMATCH，不阻塞批次），`quarantine_rate` 信号 → `enum-widen` 提案 → 同样 T0 晋升——这正是前文"坏行进隔离区不阻塞批次（坏行率 = RSI 信号）"与循环的接点。

## 宪法（循环不可触碰面，机器提案触碰即降 T3）

① 引擎与求值器本体 ② EvalSuite 通过线（不可自降）③ Cedar 放宽方向 ④ marking 与属性所有权 ⑤ tier 定义与预算 ⑥ 审计本身。
**Tier graduation**：同类变更连续 10 次干净晋升 + 人工批准才可 T1→T0——且升级本身是 T3。
