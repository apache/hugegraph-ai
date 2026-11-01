# 02 · 本体模型与 DSL（core/models.py · core/loader.py · core/validator.py）

> 所属：[架构文档](../README.md#第一部分--架构文档part-i--architecture)

**中文** | [English](../../en/architecture/02-ontology-model-and-dsl.md)


**11 种资源 = 9 种平台资源 + 2 种清单资源**，全部是 `apiVersion: ontogeny/v1` 的 YAML，目录即包，Git 即真源；环境引用 `${VAR}` 运行期注入，包内无密钥。语义层（对象·链接）与动力学层（动作·函数·策略）配对，外加派生层（投影）、Agent 层（插件）与自进化层（评测/治理基线）。分组口径以 [00 · 种类分类学](00-kind-taxonomy.md) 为准。

## 11 种资源一览

| 组 | kind | 层 | 职责与关键字段 |
|---|---|---|---|
| 清单 | `Store` | 数据面 | 存储绑定：`type`（postgres/sqlite/duckdb/csv/parquet/iceberg）· `connection: ${DSN}` · `access`（read-write 是动作写回前提） |
| Core | `ObjectType` | 语义 | 名词：`primaryKey` · `properties`（类型/required/**owner**/marking/**derived**）· `backing`（store + mode + source + mapping + **sync**） |
| Core | `LinkType` | 语义 | 关系：`cardinality`（1:1 / 1:N / M:N）· join（**foreign-key** 或 **join-table**） |
| Core | `Action` | 动力学 | 动词：五段式（parameters → rules → policy → effects → audit）；声明式或 `execution: function` |
| Extension | `Function` | 动力学 | 逻辑：`runtime`（python/ts）· `entry` · `capabilities`（read-objects / llm）· `publish`（版本锚定） |
| Core | `PolicySet` | 治理 | Cedar 策略文件（`source: *.cedar`）；未显式声明用包默认策略 |
| Adapter | `Projection` | 派生 | 图投影：`include`（白名单属性+链接，**marking 禁入**）· deletion · indexes · `endpoint` |
| Extension | `AgentPlugin` | Agent | Agent 即资源：`principal`（冻结身份=权限面）· `tools.allow` · `approval.writes` · `budget`（steps/wall_ms/writes） |
| Extension | `EvalSuite` | 自进化 | 选择函数：queries（形状/延迟/行数）+ replays（动作回放）+ coverage（隔离率）——**全部确定性可求值** |
| Baseline | `EvolutionPolicy` | 自进化 | 治理基线文件：loop · observability · tiers T0–T3（mutations+预算）· graduation——**仅人可改** |
| 清单 | `Ontology` | 清单 | 包清单：name/display/version/imports（包依赖，模板市场基础） |

## 示例：两种派生

```yaml
# 表达式派生（读时计算，不落列）
qty_completed: { type: integer, owner: ontology }
qty_planned:   { type: integer, required: true }
completion_rate:
  type: "decimal(6,2)"
  derived: "(qty_completed / qty_planned) * 100"
```

```yaml
# 函数派生（跨对象，物化落列）
open_mo_count:
  type: integer
  display: 未关闭维修单数
  derived:
    kind: function
    entry: maintenance_state.py:open_mo_count
    object_param: obj
    triggers: [maintenance-order]   # 跨对象触发
```

**分界**：表达式派生只能用本行字段、读时计算；函数派生可 `ontogeny.query` 其他对象甚至调 LLM，因此由派生 Worker **物化落列**（写后批量重算，最终一致）。

## 表达式语言 mini-expr（规则 / 派生 / 效果 / 断言共用）

自研 Pratt 解析器（词法 → AST → 树求值，**禁 eval()**），非图灵完备；解析缓存 + 静态分析（`analyze()` 收集引用供校验器核对）。

| 类别 | 支持 |
|---|---|
| 运算 | 算术 · 比较 · 逻辑 `and or not` · `in` · `has` · `??` 空合并 |
| 根 | `target.*` · `parameters.*` · `principal`；派生表达式允许**裸字段名糖** |
| 函数 | `now()`（注入时钟，回放可复现）· `user()` · `newId('前缀')`（引擎序列号） |
| 时间语义 | ts − ts → 毫秒；naive/aware 混用自动归一 UTC（修复过派生全空的时区 bug） |
| 字面量 | 效果值裸标识符 = 枚举字面量（`status: CLOSED`） |

## 校验器与 lint（发布闸门）

**validate（阻断发布，20+ 检查码）**：引用完整性 · join 键类型 · 主键自洽 · **动作 set 源属属性 = 错**（所有权）· 派生禁 mapping · 投影 **marking 禁入** · 表达式静态分析 · 函数派生 entry 形状 · EvalSuite 引用 · 治理基线标记。

**lint（团队规范，可豁免）**：display/description 必填 · kebab-case · 派生链 ≤2 · webhook 动作需收窄 audit.fields——规范不挡发布但留痕。
