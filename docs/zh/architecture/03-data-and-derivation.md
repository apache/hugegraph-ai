# 03 · 数据与派生链路（stores/ · action/outbox.py · functions/derivation.py）

> 所属：[架构文档](../README.md#第一部分--架构文档part-i--architecture)

**中文** | [English](../../en/architecture/03-data-and-derivation.md)


## 3.1 属性级所有权（谁是真的源）

| owner | 同步（sync） | 动作（Action） | 典型字段 |
|---|---|---|---|
| `source`（默认） | 拥有插入与更新，全量推送照单全收 | 禁止修改（校验期拦截） | 编号、名称、时间戳等台账字段 |
| `ontology` | 仅初次播种，**永不覆盖** | 唯一合法写者 | status、qty_completed 等业务状态 |

声明即解决"源系统全量推送冲掉动作状态"的经典事故。空 mapping = 同名直映（全 source）；派生属性自动 ontology。

## 3.2 同步引擎（三策略 + 四铁律）

| 策略 | 适用 | 机制 | 保证 / 限制 |
|---|---|---|---|
| `snapshot` 全量快照 | 初始化 / 小表 | 全量 → 按 PK upsert；**缺席即归档**（可关） | 幂等，随时重跑 |
| `watermark` 水位增量 | 90% 场景 | `水位列 > 上次水位`；水位**提交后**才前进 | 默认不见删除——需软删标记或 changelog |
| `changelog` CDC 消费 | 高频 / 删除感知 | 消费 Debezium changelog（**采集不自建**） | 消费者就位，依赖 Kafka 源 |

**四条铁律**：① 批次原子幂等 ② at-least-once ③ 删除语义显式声明 ④ **坏行进隔离区不阻塞批次**（坏行率 = RSI 信号）。schema 漂移 → 告警停写，mapping 走 PR。

## 3.3 outbox：派生数据的唯一出口（四消费者独立游标）

| 消费者 | 做什么 | 失败语义 |
|---|---|---|
| `webhook` | POST 白名单出站 | 白名单外告警并消费；`${VAR}` 未配 → 告警并消费，**修复后重放**（不回滚业务事务） |
| `projection` | 行变更 → HugeGraph 点边 | 同对象按 outbox id 单调；upsert 幂等，失败游标回退重试 |
| `derivation` | 入队待重算（含 triggers 跨对象路由） | drain 失败仅告警；下次续跑 |
| `sse` | 实时推流 | 订阅者队列满 → 丢事件（不影响存储） |

## 3.4 派生 Worker：函数派生物化（单批 = 单进程 = 单事务）

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
