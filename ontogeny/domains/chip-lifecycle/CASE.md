# 芯片产品全生命周期案例（chip-lifecycle）

## 1. 业务流程
#### 名词说明 

| 词 | 一句话 |
|---|---|
| 流片 tapeout | 把验证过的电路设计送到晶圆厂做第一批样片 |
| 晶圆 wafer | 一片硅圆片，可切出成百上千颗芯片 |
| 批次 lot | 同一次投产的一组晶圆，质量追溯的基本单位 |
| CP 测试 | 晶圆切开后对每颗芯片通电测试 |
| 良率 yield | 一批里合格芯片的比例 |

### 1.1 流程概览

```text
需求    create-requirement → change-requirement（受控变更）
研发    create-design-module → create-tapeout-version → tapeout（送厂流片，A0/A1/B0…）
制造    start-lot → complete-process-step（工序+设备）→ record-wafer-test（CP 良率）
         hold-lot 冻结在制批次 · reassign-step 改派设备 · retract-wafer-test 撤回误录
售后    open-field-failure（登记客户失效/退货）
闭环    raise-*-alert → analyze-*（函数）→ record-*-root-cause → 结论写回
```

前向问题是「**改一条需求，影响哪些模块、版本、在制批次**」；
反向问题是「**客户手里坏掉的芯片，出自哪个批次、哪台设备、哪个设计**」。

### 1.2 对象与关系

| 对象 | 含义 | 链接 |
|---|---|---|
| requirement | 需求：标题、优先级、规格 | ← requirement-modules |
| design-module | 设计模块：承担需求的电路块；文档抽取的引用类型 | requirement-modules · version-includes · ← design-fmea-notes |
| tapeout-version | 流片版本：PLANNED → FAB → QUALIFIED；`mask_cost` 为密级字段，`fab_lag_h` 为派生属性 | version-includes · version-lots |
| wafer-lot | 晶圆批次：某版本一次投产的晶圆组 | ← version-lots · lot-steps · lot-tests |
| process-step | 工艺步骤：批次经过的工序与设备 | ← lot-steps · ← step-equipment |
| equipment | 设备：光刻机、刻蚀机、沉积腔；工序可改派到另一台 | step-equipment |
| wafer-test | CP 测试：测多少、坏多少；**良率告警与根因是它的状态字段** | ← lot-tests |
| customer | 客户 | customer-failures |
| field-failure | 失效单：症状、失效模式；**聚集告警与根因是它的状态字段**；初始不挂批次（§3） | ← customer-failures |
| fmea-note | 从 FMEA 文档抽取的失效模式（§2.5） | ← design-fmea-notes |

预警不是独立实体，是挂在测试单 / 失效单上的状态字段。

### 1.3 角色与权限（lifecycle.cedar）

| 角色 | 可执行动作 | 行级条件 |
|---|---|---|
| product | create/change-requirement · create-design-module · create-tapeout-version · tapeout | change 仅 `status != CLOSED`；tapeout 仅 `PLANNED` |
| fab | start-lot · complete-process-step · hold-lot · reassign-step · record-wafer-test · retract-wafer-test · raise-yield-alert · record-root-cause | complete 仅 `!= COMPLETED`；hold 仅 `RUNNING` |
| cqe | open-field-failure · raise-surge-alert · record-failure-root-cause | — |

默认拒绝；人与 Agent 过同一个策略引擎，没有第二扇门。

### 1.4 种子数据（贯穿全文的事实）

- **REQ-101**：客户 ASTRA 要求 IO 端口 ESD ±8kV 接触放电、漏电 <10 nA——HIGH 优先级，公差紧。
- **DSG-201**（IO 环 & ESD 保护）承接 REQ-101、在 TO-A0；**DSG-211** 是它在 TO-A1 的改版（钳位加大到 ±12kV）。
- **TO-A0** FAB；**TO-A1** PLANNED；**TO-B0**（X2 项目）FAB。
- **LOT-2417** 刻蚀走 **EQ-07**，CP 良率 **82%**（WT-501：200 测 36 坏）；**LOT-2418** 同版本但刻蚀走 **EQ-09**，良率 96%——同设计、不同机台的对照组。**LOT-2419** 在制，刻蚀正跑在 EQ-07 上。
- **FF-8001/8002/8003**：两周内 ASTRA 退回 3 颗，IO 漏电超标 / ESD 闩锁。

## 2. 分析与预警：Action 与 Function 怎么用

**Function 算答案，Action 改世界。** 函数在沙箱内只读，可读对象由 `capabilities`
声明；动作是唯一写入口，走 参数 → 规则 → 策略 → 效果 → 审计 五段式。

### 2.1 四个函数，每个生命周期阶段一个

| 函数 | 可读 | 回答什么 |
|---|---|---|
| requirement-impact | requirement · design-module · tapeout-version · wafer-lot | 需求变更的前向影响面：模块、版本、在制批次与在制晶圆数 |
| analyze-yield-loss | wafer-test · wafer-lot | 良率根因候选：工艺漂移 or 设计边缘 |
| analyze-field-failure | field-failure · customer | 失效根因候选与证据建议 |
| yield-pareto | wafer-test · process-step | 按批次排良率损失，带工艺路线（步骤@设备） |

`analyze-yield-loss` 的逻辑（损失 = 1 − 良率）：>10% → PROCESS 0.82；5%–10% →
0.66；始终附 DESIGN 0.55；候选按置信度降序；损失 >5% 建议 HOLD，否则 REVIEW。
`analyze-field-failure` 始终给 PROCESS 0.55（建议按出货追批次）；PARAMETRIC 失效
再加 DESIGN 0.62（指向需求公差与 FMEA 记录）。置信度是启发式分值，不是结论；
函数不写库。

### 2.2 告警与写回（Action）

| 动作 | target | 关键参数 | 规则 |
|---|---|---|---|
| raise-yield-alert | wafer-test | severity ∈ {INFO,WARN,MAJOR,CRITICAL}；kind ∈ {YIELD_DROP, SPC_OOC} | `result != 'PASS' or defect_qty > 0` |
| raise-surge-alert | field-failure | severity 同上；kind ∈ {DEFECT_SURGE} | `status != 'CLOSED'` |
| record-root-cause | wafer-test | root_cause；class ∈ {DESIGN,PROCESS,MATERIAL,ASSEMBLY,PLANNING}；confidence | `confidence <= 1` |
| record-failure-root-cause | field-failure | 同上 | 同上，**并把失效单置为 ANALYZED** |

效果都是把告警 / 根因四字段写回目标对象；审计记录单号、写前值与全部参数。

### 2.3 场景一：制造段良率（正向闭环）

```text
call  analyze-yield-loss(WT-501)                    → 82% 良率：PROCESS 0.82 / DESIGN 0.55，HOLD
graph WT-501 → LOT-2417 → 刻蚀 EQ-07；对照组 LOT-2418（EQ-09）96%
     → TO-A0 → DSG-201 → REQ-101（公差紧）
act   raise-yield-alert(WT-501, MAJOR, YIELD_DROP)  → alert_status = OPEN
act   record-root-cause(WT-501, "EQ-07 刻蚀窗口偏移", PROCESS, 0.82) → 修订落库
```

函数最高分恰好是 PROCESS，但选它的理由是对照组与 FMEA 证据（FM-DSG201-02，
RPN 105），不是分数本身。函数给候选，图遍历取证据，人定结论，动作留痕。
这条写回的根因会在 §3.3 被售后直接复用。

### 2.4 场景二：需求段变更（前向影响）

```text
call requirement-impact(REQ-101)
  → DSG-201、DSG-211 · TO-A0、TO-A1 · LOT-2419（RUNNING，25 片在制）
```

ESD 加严改 A1 版——影响面一条函数算清。前向与反向共用同一条对象链，
这正是把四段建成一张图的意义。

### 2.5 文档智能：FMEA 证据挂到设计模块

`data/docs/fmea-io-esd-dsg201.md` 是一份完整模块 FMEA：7 条失效模式（S/O/D、
RPN、建议措施）+ 检测覆盖 + 围堵规则。要让机器能按模块反查，需把表格变成图上
的节点：

```text
新建任务 → 选 fmea-io-esd-dsg201.md → scope(fmea-note + design-fmea-notes)
  → Run（外部抽取 Agent 按本体 schema 抽取）→ Review（人逐字段核对）
  → Confirm（一个事务写入 7 个 fmea-note + 7 条边）
```

关键约束：抽取 Agent（`tools/doc_agent_fmea_module.py`，确定性表格解析）只按
schema 白名单输出；身份按标题哈希出稳定 ID，重复导入走 `fill-empty` 合并；
`Module: DSG-201` 只解析**已存在**的 design-module 行，绝不新建；确认前不落库。
daemon 的 `ONTOGENY_DOC_AGENT_CMD` 路由器按 schema 派发：含 design-module 引用走
芯片 FMEA agent，否则回落到通用参考 agent。

结果 `DSG-201 ──design-fmea-notes──▶ fmea-note ×7`：FM-DSG201-01「ESD 闩锁超
8kV」（钳位面积恰好按 ±8kV 设计、无余量，RPN 96）与 FM-DSG201-02「IO 漏电超
10 nA」（刻蚀窗口偏移，RPN 105，唯一超 100 的围堵项）正是 §2.3 和售后失效要用的
两条证据。

## 3. RSI：链路断了，循环怎么补

### 3.1 循环做什么

本体第一版建不全。RSI 把「发现缺口 → 提案 → 评测 → 晋升 → 热加载」做成每 30
分钟一拍、每拍落库的闭环（`evolution.yaml`）：

| 拍 | 动作 | 产物 |
|---|---|---|
| 信号 | 8 种检测器扫 168h 遥测：查询日志 · 动作轨迹 · Agent 轨迹 · 同步隔离区 | `ontogeny_evolve_signal` |
| 归因 | 信号 → 缺口假设，附证据计数 | gap |
| 提案 | 启发式或 LLM 生成白名单内变异，必须带 rationale | `ontogeny_evolve_proposal` |
| 评测 | 候选包副本上跑 EvalSuite，线上不动 | report |
| 晋升 | T0–T3 分层 + 周预算 10 次/周 | `ontogeny_evolve_budget` |
| 生效 | publish + reload 热切换；回滚 = 切回上一版包目录 | Git diff |

LLM 只出变异和理由，**通过与否只由确定性评测决定**（本包评测门
`lifecycle-flow-suite`：4 条查询断言 + complete-process-step 90 天回放）。

### 3.2 诊断示例：售后处置决策缺数据

**决策**：ASTRA 两周退回 3 颗同症状芯片——**冻结 LOT-2419（还在 EQ-07 上刻蚀的
25 片在制），还是让 EQ-07 停机大修**。

**缺口**：回答需要知道失效芯片出自哪个批次，但 field-failure 只建模了客户与症状；
analyze-field-failure 只读失效单与客户。制造段已写回的根因（EQ-07 漂移）售后看不见
——**追溯链在「售后 → 制造」之间断了，缺口横跨两段，单看任何一段都发现不了**。

这个缺口在本包里是**真实埋好的**：源表 `field_failures` 带 `lot_id` 列（种子已填），
本体不声明它——按批次过滤抛 `NotFoundError`，正是 `unmapped_filter_field` 检测器
要抓的信号。

**全域信号**（同一 168h 窗口，四类遥测各自报告）：

| 检测器 | 证据 | 通道 |
|---|---|---|
| unmapped_filter_field | field-failure 按 `lot_id` 过滤 23 次——源表有列，本体未建 | 自动提案 add-optional-property |
| quarantine_rate | 源表送来 `failure_mode = ESD_LATCHUP`，枚举不含，整行进隔离区 | 自动提案 enum-widen |
| approval_reject_rate | CQE 助手起草的根因写回被拒 40%——审批人要批次证据 | 仅呈现 |
| hot_query | 「按批次查失效」重复 ≥3 次 | 固化为评测用例 |

**提案 → 评测 → 晋升**：

```text
#61 add-optional-property field-failure.lot_id   → T0 自动合并（评测全绿 + 周预算内）
#62 enum-widen failure_mode += ESD_LATCHUP       → T0
#63 function-change analyze-field-failure 增读批次维度 → T2 金丝雀（评测绿 + 影子双跑 + 人工审批）
```

若 LLM「顺手」提议放宽 record-root-cause 审批（policy-loosen），promoter 抛
`BaselineViolationError` 转 `awaiting_human`——T3 没有自动路径。

### 3.3 链路补全后：一颗坏芯片的旅行

```text
FF-8001 ──lot_id──▶ LOT-2417 ──工艺──▶ 刻蚀 EQ-07
                       │                    │
                     WT-501（良率 82%）     §2.3 已写回根因：PROCESS，EQ-07 漂移
                       │
                     TO-A0 ─▶ DSG-201 ─▶ REQ-101（公差紧）
                               └─▶ fmea-note ×7（FM-DSG201-01 闩锁 RPN 96）
```

- **决策有据**：act hold-lot 冻结 LOT-2419，EQ-07 例行检修即可，不必停机大修；
- **闭环写回**：record-failure-root-cause 写 PROCESS、置信度 0.85，失效单转 ANALYZED；
- **反哺需求**：证据链暴露 REQ-101 公差过紧，而 TO-A1/DSG-211 已在计划中——
  **售后的一次退货，最终改回了最前端的一条需求。**

### 3.4 边界

- 变异外包给 LLM，选择不外包：无 rationale 的提案入口即丢弃；通过线由脚本定。
- T3 面——策略放宽、密级、所有权、评测通过线、破坏性迁移——机器不可执行。
- 每拍落库：信号、提案、评测报告、晋升记录可审计、可重放、可回滚。
- 周预算封顶，超限抛 `BudgetExceededError`：宁可停一拍。

## 4. 与 Agent 协同

### 4.1 三个 Copilot，一段一个

| Agent | 身份 | 读 | 算 | 写（需审批） |
|---|---|---|---|---|
| product-copilot | product | requirement · design-module · tapeout-version · wafer-lot · fmea-note | requirement-impact | create/change-requirement |
| fab-copilot | fab | lot · process-step · wafer-test · tapeout-version · fmea-note | analyze-yield-loss · yield-pareto | start/hold-lot · complete-process-step · record-wafer-test · raise-yield-alert · record-root-cause |
| cqe-copilot | cqe | field-failure · customer · wafer-lot · wafer-test · design-module · fmea-note | analyze-field-failure | open-field-failure · raise-surge-alert · record-failure-root-cause |

三者均带 `describe_ontology`、`traverse_graph`；`approval.writes: confirm`；
预算 30 步 / 90 s / 3 写。Agent 是 DSL 声明的平台资源——身份即权限面：Cedar 对该
角色授什么，Agent 就能做什么，不多一分；工具面 = 编译目录 ∩ allow − deny，
只收窄不放大。

### 4.2 一次写入的旅程

```text
open_session     插件 + 任务 → 冻结身份与预算
call_tool(read)  直接执行，落 ontogeny_agent_step
call_tool(write) 免费 validate 预演 → 挂审批队列 → 持同动作许可的人批准 → 五段式执行 → ontogeny_revision
budget           steps / wall_ms / writes 任一超限 → 会话终止
```

Agent 不能自批；每步轨迹可回放，也是 RSI 的信号源。

### 4.3 旗舰会话：cqe-copilot 的一次售后回溯（§3 之后）

```text
1. search_field_failure(FF-8001)                        → ASTRA，IO 漏电超标，PARAMETRIC
2. call_analyze_field_failure(FF-8001)                  → DESIGN 0.62 / PROCESS 0.55
3. traverse_graph(FF-8001 ⇢ LOT-2417 ⇢ WT-501)          → 制造段根因坐实批次关联
4. search_field_failure(filter: lot_id=LOT-2417)        → 同批 3 单，两周内
5. act_raise_surge_alert(FF-8001, MAJOR, DEFECT_SURGE)  → pending-approval
6. act_record_failure_root_cause(FF-8001, "EQ-07 刻蚀批次性偏移", PROCESS, 0.85) → pending-approval
7. 质量总监批准                                          → 两条修订落库
```

6 步、2 次写，预算内。助手做查、算、取证、起草；判断与批准是人的。
