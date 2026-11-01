# 00 · 种类分类学（KIND TAXONOMY）

> 所属：[架构文档](../README.md#第一部分--架构文档part-i--architecture) · 源：`core/kinds.py` · `GET /meta/ontology` 的 `kinds` 字段

**中文** | [English](../../en/architecture/00-kind-taxonomy.md)

本文是 **kind 数量与分组的唯一权威**。其余文档、控制台架构板、`/meta/ontology` 都引用这张表；如果它们与本文冲突，以本文和 `core/kinds.py` 为准。

## 一句话结论

**11 种 DSL 资源 = 9 种平台资源 + 2 种清单资源。**

- **平台资源（platform resource）**：平台的构成主体——会被编译进运行时、有独立校验块、有独立生命周期与 review 责任人的声明式资源。
- **清单资源（manifest）**：随包同行的绑定与包清单（`Store`、`Ontology`）。它们不是平台的构成主体，**不算平台资源**。

## 九个平台资源

| 组 | kind | 层 | 变更频率 | 谁 review | 合并会失去什么 |
|---|---|---|---|---|---|
| **Core** | `ObjectType` 对象 | 语义 | 高 | 数据 / 领域 | 业务名词无处声明 |
| **Core** | `LinkType` 链接 | 语义 | 高 | 数据 / 领域 | 关系与多跳追溯无处声明 |
| **Core** | `Action` 动作 | 动力学 | 中 | 流程 / 领域 | **唯一写入口**消失，审计与策略失去唯一锚点 |
| **Core** | `PolicySet` 策略 | 治理 | 低 | 安全 | 默认拒绝与行级授权无处声明 |
| **Extension** | `Function` 函数 | 动力学 | 中 | 平台 | 只读计算与“能算不能写”的沙箱边界消失 |
| **Extension** | `AgentPlugin` 智能体 | Agent | 中 | AI 治理 | Agent 只能用调用者身份 → 隐式提权 |
| **Extension** | `EvalSuite` 评测 | 自进化 | 中 | 评测 / 领域 | 晋升失去确定性选择函数，只剩 LLM 判分 |
| **Adapter** | `Projection` 投影 | 派生 | 低 | 图 / 平台 | 仅失去“发布期拦截 marking 进图”；图本就是可缺席的加速器 |
| **Baseline** | `EvolutionPolicy` 治理基线 | 自进化 | 极低、仅人可改 | 架构委员会 | RSI 的 T3 保护失去物理落点 |

> 治理主线：`Action`（唯一写门）、`EvalSuite`（选择框）、`EvolutionPolicy`（带 `人改` 标签，仅人可改）。

## 两个清单资源（不是平台资源）

| kind | 层 | 职责 | 为什么不是平台资源 |
|---|---|---|---|
| `Store` | 数据面 | 存储绑定：`type` · `connection: ${DSN}` · `access` | 是“数据挂在哪”的绑定，不参与语义、写路径或治理决策 |
| `Ontology` | 清单 | 包清单：name / display / version / imports | 是包的元数据，不被编译进运行时快照 |

## 为什么是九个，而不是四个或十五个

判断标准只有三条，缺一不可：

1. **正交**：这个概念不能被其他 kind 表达。`Function` 不能并进 `Action`（它必须能读、能算、且**永不写库**）；`EvolutionPolicy` 不能并进 `EvalSuite`（考题与考试规则的生命周期、评审人、爆炸半径完全不同）。
2. **独立生命周期**：变更频率、review 人、回滚方式不同。把“每周都变的 Object”和“几乎不变的治理基线”塞进同一个文件，等于把签字权也合并了。
3. **治理可映射**：它对应一个必须有人签字的决策面。RSI 的 T0–T3 分层判定依赖“变的是哪个 kind/字段”；kind 边界模糊，tier 就无法自动分类。

反过来，**数量本身不是判据**。Kubernetes 有 70+ 内置 kind 仍然可用，因为它分层（core / CRD）且有默认值；dbt 有 6 种节点，因为每种对应不同执行语义。真正的反模式是“一个万能 config 装下所有语义”——校验器无法静态检查、审计无法归因、RSI 无法分 tier。

## 准入门槛（新增 kind 必须回答）

1. 现有 kind + 扩展字段为什么表达不了？
2. 它的 review 责任人是谁？变更频率与爆炸半径是什么？
3. 它是否需要独立的校验块、编译产物或运行时路径？
4. 它进 `core` / `extension` / `adapter` / `baseline` 哪一组？为什么？
5. 如果答案不成立，走 **extension 命名空间**，不要往核心塞。

新增一个 kind 的改动面应当恰好是：`core/kinds.py` + 一张冻结测试表 + 文档表格。若需要改五个地方，说明抽象还没收敛。

## 最小可用包

分类学的表面积是 11，**入门门槛是 2**：

```yaml
# ontology.yaml + stores/main.yaml + objects/product.yaml
# 1 个 Store + 1 个 ObjectType = 可加载、可校验、可查询的本体
```

`Action` / `PolicySet` / `Function` / `AgentPlugin` / `Projection` / `EvalSuite` / `EvolutionPolicy` 全部可以缺席。第一次建模不需要理解九个平台资源。

## 代码与契约

| 位置 | 作用 |
|---|---|
| [`core/kinds.py`](../../../server/ontogeny/core/kinds.py) | `KINDS` / `BY_KIND` / `DIR_KINDS` / `PLATFORM_KINDS`，唯一注册表 |
| [`core/models.py`](../../../server/ontogeny/core/models.py) | 11 个 Pydantic 模型；导入期断言注册表与模型一致 |
| `GET /meta/ontology` → `kinds` | 对外发布的分类表（`kind` / `group` / `layer` / `core` / `platform`） |
| [`ArchBoard.tsx`](../../../web/src/pages/dashboard/ArchBoard.tsx) | 架构板按 `kinds` 渲染芯片；只保留“怎么画”，不再持有名单 |
| [`tests/test_kind_registry.py`](../../../tests/test_kind_registry.py) | 冻结 `(kind, group)`；新增/删除 kind 必须显式改这张表 |
