# 05 · Agent 治理子系统（agent/broker.py · agent/engines/ · mcp_server.py · AgentPlugin）

> 所属：[架构文档](../README.md#第一部分--架构文档part-i--architecture)

**中文** | [English](../../en/architecture/05-agent-governance.md)


Agent 是 **DSL 里声明的一等资源**：插件自带冻结身份（权限面）、工具白名单、审批模式与预算。
MCP 工具面随服务启动**挂载在 `/mcp`**（streamable HTTP · JSON 模式）。每个工具带保留参数
`plugin` + `session_id`——带会话的调用汇入 **broker.call_tool 唯一门**，
在插件身份、该会话预算与工具目录内执行并落轨迹；不带会话则**只读**（写入返回
`WRITE_REQUIRES_SESSION`；缺省 `mcp-agent` 共享身份被角色门控策略全部拒绝——
故意设计：不声明就什么都做不了）。

**驱动者认证**：agent REST 端点与 /mcp 记录（生产关闭 dev_auth 时强制）登录 driver，轨迹逐步可归责（step.driver = engine / 用户 / anonymous）；
**视图过滤**：tools/list 带 `X-Ontogeny-Plugin` 头只看该插件的有效目录（纯视图，执法仍在 broker 的冻结目录）。

```yaml
# agents/sales-copilot.yaml
apiVersion: ontogeny/v1
kind: AgentPlugin
metadata: { name: sales-copilot }
spec:
  principal:
    id: "agent:sales-copilot"
    Role: [sales_rep]        # ← 权限面（I1）
    site: north
  transport: { kind: http }
  tools:
    allow: [ describe_ontology, search_sales_order,
             search_customer, traverse_graph,
             act_confirm_sales_order ]
  approval: { writes: confirm }   # 写入挂审批
  budget: { steps: 30, wall_ms: 90000,
            writes_per_session: 3 }
```

**一次 Agent 写入的旅程（agent/broker.py）**：

1. **open_session**：插件 + 任务 → 会话（预算激活）
2. **call_tool**：工具目录校验 → 身份切换为插件 principal
3. **读工具**：只读执行，留步骤记录
4. **写工具**：先 validate（免费预演）→ 审批门 → 挂起待批，**未批准前不执行**
5. **人工决策**：持同动作许可者批准/拒绝 → 批准后才执行五段式
6. **预算**：steps / wall_ms / writes 任一超限 → 会话终止；**不可跨插件跳转**（防逃逸）

**引擎选择（AgentEngineSpec）**（外部 · 第三方 LLM / Agent 运行时）：`engine.kind` 三选一：
**builtin-llm**（平台内置 LLM 工具循环——**已实现**，由 Apache Ollama 驱动：plan → 选工具 → 观察 → … → final；LLM 只选工具、事实只来自工具结果，每步入 `ontogeny_agent_step`）·
**external-pull**（**默认**：第三方 Agent 运行时经会话协议拉取驱动——外部 Agent 以插件身份接入，平台只管治理）·
**external-push**（平台委托给引擎 HTTP 端点，字段预留）。**POST /agent/sessions/{id}/run** 按此分发。

## Agent API（/agent，9 端点）

| 端点 | 方法 | 说明 |
|---|---|---|
| `/agent/plugins` | GET | 插件目录（身份/工具/预算/审批） |
| `/agent/sessions` | POST/GET | 开会话 / 列表（按插件过滤） |
| `/agent/sessions/{id}` | GET | 会话详情 + 步骤轨迹 |
| `/agent/sessions/{id}/tools/{tool}` | POST | **单门**执行：写工具返回 pending-approval 或结果 |
| `/agent/sessions/{id}/run` | POST | **引擎分发**：把会话交给插件声明的引擎驱动（builtin-llm 进程内循环 / external-push 委托远端；external-pull 返回指引） |
| `/agent/sessions/{id}/finish` | POST | 结束会话（result 归档） |
| `/agent/approvals[/{id}/decision]` | GET/POST | 审批队列与决策（决策人需持同动作许可） |

前端「智能体控制台」（/agent）可视化插件、会话轨迹与审批队列。**Agent-eval**：对插件会话跑评测（工具选择正确性），防 Agent 行为回归。

## 5.1 三扇门：外部访问本体的三种方式

外部消费者触达本体有三条通道，**权限闸是同一个策略引擎（按身份裁决），会话不是门禁而是自治运行的保险装置**：一次性查数据走 ①② 即可；让 Agent 自主跑完整任务（多步、可能写入、要轨迹）才需要 ③ 把运行套进预算与审批。

| 维度 | ① REST API（服务直连） | ② MCP Server（Agent 工具面） | ③ 会话协议（受治理的 Agent 运行） |
|---|---|---|---|
| 入口 | `/api/v1/objects\|graph\|actions\|functions\|meta\|audit…`（79 操作，见 [参考手册 12.4](../usage/12-reference.md#124-api-核心端点按域分组--全量与实时契约以-openapijson-为准共-79-操作70-路径)） | `/mcp`（streamable HTTP · JSON/无状态）：目录工具 `describe_ontology` · `search_{t}` · `traverse_graph` · `call_{f}` · `act_{a}` + 会话管理工具 `agent_open_session · agent_get_session · agent_list_sessions · agent_finish_session`（按编译产物自动生成，promote 后自动重建） | `POST /agent/sessions` 开会话 → `…/tools/{tool}`（单门）· `…/run`（引擎分发）· `…/finish` |
| 身份 | 每次调用自带 principal（dev 模式走 `X-Ontogeny-Principal` 头） | 带 `plugin` → 插件委托身份；缺省 `mcp-agent` 共享身份（**零权限，角色门控策略必拒——故意设计**） | 开会话时**冻结**的插件 principal 快照；中途修改插件定义不影响运行中的会话 |
| 可读 | 对象查询 / 单读（掩码后）/ 关系导航 / 聚合，图 explore / traverse，本体快照与血缘，审计修订流 | 本体快照（`describe_ontology`）、按类型检索（filter DSL）、多跳遍历（`traverse_graph`）；按插件目录收窄 | 同 ② 的工具面，但被插件白名单收窄；另可读会话详情 + 步骤轨迹（`GET /agent/sessions/{id}` 或 MCP `agent_get_session`） |
| 可操作 | Action 五段式执行 + 免费干跑 validate，Function 沙箱调用，admin 运维（publish / sync / derive / 投影重建） | `act_{a}` / `call_{f}`；带 `session_id` 时与 ③ 完全同门（broker.call_tool） | 同 ②，但一律经 **broker.call_tool 唯一门**；写工具先免费 validate（预演不计步） |
| 权限闸 | 三者过**同一个策略引擎**（agent 与人类共用策略面，无第二扇门）；②③ 另有工具目录交集 `catalog ∩ allow − deny`，**只收窄、不放大**（不变量 I1） — 三列共用 |||
| 写入审批 | 无审批队列——规则 + 策略通过即执行，留 `ontogeny_revision` | 带会话：同 ③（confirm 挂审批 / never 拒绝 / auto 白名单）；无会话：一律 `WRITE_REQUIRES_SESSION` | 按插件 `approval.writes`：**confirm** → 挂审批队列等人批（拒绝退额度）· **never** → 只读插件直接拒绝 · **auto** → 仅 `auto_actions` 列表内免批 |
| 预算 | 无（调用方自律） | 带会话：计入 steps / writes 硬闸（超限返回 `AGENT_BUDGET_EXCEEDED`）；无会话：无 | **steps / writes 硬闸**，超限返回结构化 `AGENT_BUDGET_EXCEEDED` 停机（`wall_ms` 已随会话冻结，v1.2 起按每次 run 的墙钟强制执行，start_run 重置） |
| 轨迹审计 | `ontogeny_revision`（动作修订流） | 带会话：逐步 `ontogeny_agent_step`（含 `thought` 自述）+ `ontogeny_revision`；无会话：仅 `ontogeny_revision` | 逐步 `ontogeny_agent_step`（UI 可完整回放，也是 RSI 信号源）+ `ontogeny_revision` |
| 并发保护 | 无 | 带会话：running 期间非引擎调用返回 `AGENT_SESSION_RUNNING` | running 期间非引擎调用返回 `AGENT_SESSION_RUNNING`（防人与 LLM 并发写同一会话） |
| 适合谁 | 人类 UI / SDK / 脚本 / 服务集成 | Claude / ZCode / LangGraph 等 MCP 客户端：零代码接入，开会话后即可**自主跑完整任务**（或无会话做一次性只读查询） | 自主 Agent 循环**跑完整任务**（多步 · 可能写入 · 需完整轨迹与预算兜底） |

## 5.2 引擎范式：协议即契约，引擎可插拔（第三方接入）

**会话是被治理的执行容器，引擎（Engine）是驱动它的执行器**。任何引擎——第三方或内置——都通过同一套工具协议驱动会话，因而被同一套治理覆盖。范式四公理：
① **引擎永不直接触达数据**（唯一能力表面 = 工具目录，无 SQL、无旁路）；
② **插件声明"谁执行"（spec.engine），平台声明"如何被治理"**（principal/tools/approval/budget 与引擎正交）；
③ **Run 是统一动词**（`POST /agent/sessions/{id}/run` 把会话交给它声明的引擎）；
④ **轨迹完备（I4）**：引擎的每一步必须落 `ontogeny_agent_step`，UI 可完整回放，不允许轨迹外的副作用。

| 接入形态 | 引擎在哪 | 谁驱动循环 | 契约要点 |
|---|---|---|---|
| **A · external-pull** | 第三方进程（任意框架/语言） | 第三方 | 按会话协议逐步调工具；LangGraph / Claude 等 MCP 客户端即此类。plugin 里 `engine.kind: external-pull` 登记 |
| **B · external-push** | 第三方 HTTP 端点 | 平台 | 平台 POST `{session, task, tools, budget}` 给引擎端点，引擎回调工具协议直到 final。（未实现：包校验给 AGENT-ENGINE-UNIMPLEMENTED 警告） |
| **C · builtin-llm** | 平台进程内 | 平台 | 内置 LLM 工具循环（参考实现）：严格 JSON 单工具/轮，复用 `OllamaChat` 适配器；LLM 端点来自 `ONTOGENY_LLM_BASE_URL`（运行时配置，密钥不入 Git） |

```yaml
# 引擎声明（plugin spec 新增字段）
spec:
  engine:
    kind: builtin-llm   # builtin-llm | external-pull | external-push
    # external-push 另需: endpoint: https://…/drive
  principal: { … }         # 与引擎正交
  tools:     { … }
  approval:  { … }
  budget:    { … }
```

```text
# 生命周期状态机（引擎无关）
open ──run──▶ running ──┬─▶ finished   (final | error)
                        ├─▶ blocked_on_approval   # 写入挂起
                        └─▶ budget_exhausted
blocked ──(批准后) run──▶ running   # resume = 人在环确认点
```

**Engine 契约（agent/engines/ · 全部引擎实现同一接口）**：

1. **drive(session, resume)**：把会话从当前状态驱动到终态或阻塞点；只能经 **broker.call_tool** 执行
2. **工具结果信封**：{outcome, detail?, error?, approval_id?, revision_id?, budget} —— 引擎据此决策，不读其他接口
3. **外部调用隔离**：running 期间非引擎方的工具调用返回 AGENT_SESSION_RUNNING（防人与 LLM 并发写）
4. **内置无特权**：builtin-llm 只是 drive() 的第一个参考实现，与第三方走同一契约、同一状态机、同一闸门
5. **兼容规则**：工具目录是引擎 API 面——只加不改；input_schema 变更视为破坏性（走包版本）；协议字段 additive-only

**第三方最小接入（external-pull，~15 行，任意 HTTP 运行时）**：

```python
sess = post(f"{BASE}/agent/sessions", {{"plugin": "my-agent", "task": task}})
while True:
    catalog = get(f"{BASE}/agent/sessions/{sess['id']}")["tools"]
    decision = my_llm_decide(task, catalog, transcript)      # 任意框架/模型
    if "final" in decision:
        post(f"{BASE}/agent/sessions/{sess['id']}/finish", decision); break
    out = post(f"{BASE}/agent/sessions/{sess['id']}/tools/{decision['tool']}", decision["args"])
    if out["outcome"] in ("AGENT_BUDGET_EXCEEDED", "AGENT_SESSION_CLOSED"): break
```
