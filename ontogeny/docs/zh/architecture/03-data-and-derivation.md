# 03 · 数据与派生链路（stores/ · action/outbox.py · functions/derivation.py）

> 所属：[架构文档](../README.md#第一部分--架构文档part-i--architecture)

**中文** | [English](../../en/architecture/03-data-and-derivation.md)


## 3.1 属性级所有权（谁是真的源）

| owner | 同步（sync） | 动作（Action） | 典型字段 |
|---|---|---|---|
| `source`（默认） | 拥有插入与更新，全量推送照单全收 | 禁止修改（校验期拦截） | 编号、名称、时间戳等台账字段 |
| `ontology` | 仅初次播种，**永不覆盖** | 唯一合法写者 | status、qty_completed 等业务状态 |
| `document` | 不覆盖 | 只填空 + 追加证据；冲突进审核 | 文档抽取出来的说明性字段 |

声明即解决"源系统全量推送冲掉动作状态"的经典事故。空 mapping = 同名直映（全 source）；派生属性自动 ontology。

## 3.2 同步引擎（三策略 + 四铁律）

| 策略 | 适用 | 机制 | 保证 / 限制 |
|---|---|---|---|
| `snapshot` 全量快照 | 初始化 / 小表 | 单条 SQL 流式结果 → 按 PK upsert；**缺席即归档**（可关） | 幂等，随时重跑 |
| `watermark` 水位增量 | 90% 场景 | `水位列 >= 上次已提交水位`（重放相等边界）；水位**提交后**才前进 | 默认不见删除——需软删标记或 changelog |
| `changelog` | 为外部 CDC 集成保留 | 当前 SQL/CSV 源适配器不消费 Kafka/Debezium | 需要独立适配器，并非内置 CDC 服务 |

**四条铁律**：① 批次原子幂等 ② at-least-once ③ 删除语义显式声明 ④ **坏行进隔离区不阻塞批次**（坏行率 = RSI 信号）。schema 漂移 → 告警停写，mapping 走 PR。

同步是显式操作：使用服务对应的数据库 DSN 执行 `ontogeny sync <type>`，或调用 `POST /api/v1/admin/sync/{type}`。`sync.schedule` 是供外部调度器使用的声明；服务不会按它定时轮询源库。全新的 `--demo` 启动时只做一次初始同步。SQL 快照在各读取批次间保持同一个结果集，已读行被并发删除不会导致后续页移位并误归档仍存对象。这是单条源查询的快照，并非跨所有对象类型的事务。一次同步整体提交，读取分批不代表逐批提交。

隔离区中的数据库原生值会递归转换为 JSON 安全的诊断表示：Decimal/UUID 转字符串，日期时间转 ISO 文本，二进制转十六进制。坏行中的原生值不应阻止同次同步的正常行提交。

声明为 array/struct 的列会在 JSON 存储边界编码嵌套日期和时间，读取时按声明类型恢复。发布、重载、已有 registry 启动和领域激活均在提交 schema 后才切换运行时及 MCP 工具。

对象表通过部分唯一索引（`_valid_to IS NULL`）保证每个完整业务主键最多只有一个当前版本，历史版本不受影响。升级时若已有重复当前行，索引创建会清晰报错；请审查并人工修复重复数据后重试，启动过程不会自动删除数据。

对象读写会按属性声明类型转换传入的主键，字符串主键保留前导零。快照按完整业务主键元组核对存在性，不会因另一行具有相同的首个键分量而保留已删除行；被隔离的坏行只要完整主键仍可识别，就保留其上一次有效对象。

同一数据库中的领域共用物理表命名空间。发布或激活领域时，会拒绝其他领域已占用的对象表或 join-table 链接表名称，包含已退役的资源定义；请使用不同名称或独立数据库。修改 backing 或 join 类型也不释放旧资源名的保守预留；此前已跨域混用的数据不会自动拆分或恢复。切换前应暂停旧领域写入及源同步，等待在途操作结束，派发并确认全部旧事件，先处理失败投递。名称检查不提供待处理 outbox 事件的跨领域隔离或重路由。

## 3.3 outbox：派生数据的唯一出口（四消费者逐事件 receipt）

| 消费者 | 做什么 | 失败语义 |
|---|---|---|
| `webhook` | POST 白名单出站 | 白名单外告警并消费；`${VAR}` 未配 → 告警并消费，**修复后重放**（不回滚业务事务） |
| `projection` | 行变更 → HugeGraph 点边 | upsert 幂等；失败事件保持未确认，后续重试 |
| `derivation` | 入队待重算（含 triggers 跨对象路由） | drain 失败仅告警；下次续跑 |
| `sse` | 实时推流 | 订阅者队列满 → 丢事件（不影响存储） |

`ontogeny serve`（ASGI factory）会启动 outbox 消费循环，约每秒轮询一次，处理**已提交的 outbox 事件**后 drain 待重算派生；它不负责拉取源库。发布或切换领域后，循环会使用当前 dispatcher。仍可通过 `POST /api/v1/admin/outbox/dispatch` 手动触发即时处理，两条路径共用进程内锁。停机先取消并等待 worker 退出，再关闭客户端及数据库资源。

投递语义是 at-least-once：外部 POST 成功后、receipt 提交前崩溃可能导致重试，接收端应幂等。HTTP 5xx/连接失败会让该消费者对应事件保持未确认；4xx、未配置 URL 及白名单拒绝会留日志并消费，供运维修复后重放。一个消费者失败不会阻断其他消费者前进。待处理事件根据缺少的 `(consumer, event_id)` receipt 选择，低 ID 事务较晚提交也不会被高水位游标跳过。

升级后的首次处理会一次性迁移旧游标：为当时可见且 `id <= last_id` 的事件补 receipt，不盲目重发历史 webhook。旧实现早已漏掉、升级时又已可见的事件，无法自动区分是否成功投递；需按业务审计后，显式调用内部方法 `await sc.outbox.replay('webhook', from_id=..., through_id=...)`，再触发处理，这可能重复外部投递。其他消费者也支持同样的范围重放。outbox 行与对应 receipt 应协调归档。

## 3.4 派生 Worker：函数派生物化（单批 = 单进程 = 单事务）

读时表达式派生按依赖顺序求值，不受 YAML 字段顺序影响。循环节点及其下游字段返回 `null`（Python 中为 `None`）并记录 warning；不相关字段仍可正常求值。

非主键的函数派生属性在首次成功物化前可为 SQL `NULL`，即使声明了 `required`。必填派生结果为 `None` 时会保留旧有效值并继续等待重试。旧数据库中已经创建为 `NOT NULL` 的列，需要经过审查的显式迁移（SQLite 需重建表）；启动时不会自动放宽该约束。

一次 drain 的旅程（functions/derivation.py）：

1. **路由**：事件类型 → 命中的派生属性（自身类型 + `triggers` 跨对象；跨对象触发重算 owner 全表——定向失效需要解析沙箱代码，故意不做）
2. **装配**：批量取行 → `assemble_row`（与 API 同形：派生可见、时区保真）
3. **求值**：`map_rows` 一次子进程内循环全部行（可 ontogeny.query / ontogeny.llm）
4. **落列**：类型强转 → 单事务写当前版本列。**不产修订不进审计**（可重算值不污染审计）；动作决策不读它

## 3.5 图投影（可选 · 派生 · 可重建）

| 环节 | 机制 |
|---|---|
| schema 编译 | DSL 类型 → HugeGraph propertykey/vertexlabel/edgelabel；主键 → 点主键；白名单属性建二级索引 |
| 全量回填 | 对象表 → CSV → HugeGraph-Loader；**新图空间 + 原子切别名**（回填期间旧图可查） |
| 增量 | outbox 消费者逐事件 upsert / 删点级联删边（可选 keep-flagged） |
| 降级 | 端点未配 → 启动即 SQL-only（告警）；≥3 跳自动回落 SQL 递归 CTE |


## 3.6 文档数据源（抽取型 · 可选）

`Store(type: document)` 是一份语料，不是一个行源：文件按内容哈希登记，`ObjectType.backing.sync.strategy: extract` 把它绑定到本体。抽取由**外部 Agent** 完成：平台把本体编译出的 schema 与文档（文本或 base64）通过 stdin/stdout JSON 或 HTTP 交给 Agent，Agent 返回每个 chunk 的原文与图结构；平台不调用模型。协议见 [`extensions/doc-extract-agent/README.md`](../../../extensions/doc-extract-agent/README.md)。

| 阶段 | 机制 | 保证 |
|---|---|---|
抽取不会直接写对象表：上传时选择局部 scope 与 skill，先生成 `ontogeny_extract_task`，Agent 结果进入 attempt staging；人工核对/修改后 **确认** 才在一个事务里写对象、关系、断言与 outbox。已确认任务重跑产生新 revision，旧 revision 只保留审计。

| 语料登记 | 目录/glob → `ontogeny_document`（sha256） | 变更按内容判定，路径变更 = 旧文档移除 + 新文档 |
| 抽取 | 每文档一个 Task → Agent attempt staging（原文 chunks + 图 + validation） | 未确认不写对象表；重跑保留 attempt，scope/skill 快照可复现 |
| 绑定 | `documents/binder.py`：类型强转、主键/`extract.key` 身份、`extract.match` 消解、方向/端点校验 | 无稳定身份、歧义匹配、端点缺失 → 候选，绝不猜 |
| 合并 | `owner` + `extract.update`（默认 fill-empty） | 冲突只记录候选，不覆盖；`source` 属性默认不写 |
| 关系 | `LinkType.join.kind: extracted` 写入 link 表，`_provenance` 记录来源文档 | 重抽/删文档只回撤自己断言过的边 |
| 出口 | 确认后同 object 表 + outbox | 查询、Action、Policy、投影、MCP 全部照旧；`RevisionRow(action="ingest.confirm")` 留审计 |

审核面：`ontogeny_extract_candidate` 保存冲突/缺身份/端点未解析的候选，API 返回**原文 chunk + 证据引用 + 当前值 + 建议值**，人工可改写后接受；拒绝只记原因，不写对象表。隔离区（`ontogeny_quarantine`）继续承接类型不匹配等坏行，其比率与 schema 缺口一起进入 RSI 信号。
