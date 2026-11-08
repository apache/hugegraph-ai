# HugeGraph-LLM Eval SDK 架构与扩展边界

评测 SDK 面向独立 Python 项目和 GraphRAG 流程提供检索、答案与属性图的质量度量。接入示例见
[使用指南](../../hugegraph-llm-sdk/eval/README.md)；本文说明它在项目中的位置、内部层次和维护边界。

## 在项目中的位置

`hugegraph-llm-sdk/eval/` 是**度量层**：评分规则、Judge 协议和执行语义只在这里维护。整条链路的分工是

```
hugegraph-llm-sdk/src/   抽取 SDK：schema 设计 + 抽取
hugegraph-llm-sdk/eval/  独立评测 SDK：图、检索和答案的质量度量
hugegraph-llm/          应用：流程、配置、持久化、报告和 UI
```

目录嵌套仅用于组织源码：抽取包与评测包各有 `pyproject.toml`，是根 workspace 的两个独立成员。
父包只分发自己的 `src/hugegraph_llm_sdk/` 和示例，评测包独立分发 `src/hugegraph_llm_eval/`。
抽取 SDK 可按需调用评测 SDK，评测 SDK 不反向导入抽取代码；本次迁移不增加默认运行时依赖。

因此评测包既可以被外部项目单独安装使用，也可以被 GraphRAG 流程嵌入：流程每轮产出候选后调用一次
评测器，`findings` 与 `issues` 直接作为下一轮修复的输入，而不需要写回数据库或生成报告。

## 包内层次

| 位置 | 职责 |
| --- | --- |
| `contracts/` | 评测输入、记录、Judge 调用、失败分类与图项的不可变契约 |
| `evaluation/judges/` | Provider 无关的 `Judge` 协议、`JudgeSession`、分批与判分生命周期 |
| `evaluation/engine.py` / `executor.py` | 顺序保持、有界并发、重试、截止时间、取消与部分结果 |
| `integrations/{answer,retrieval,graph_extraction}/` | 三类评测器与输入物化（artifact → 结构化输入） |
| `artifacts/memory.py` | 进程内 artifact 存储，免去数据库与文件系统 |
| `samples.py` | 从普通 Python 值构造评测输入，隐藏 artifact 装配 |
| `prompt.py` / `prompt_templates/` | 评测指令与 rubric，版本随代码维护 |

依赖方向是单向的：SDK 只依赖 Pydantic（以及可选 extra 的第三方库），不得导入应用配置、UI、图客户端或
日志初始化；厂商依赖只在对应适配器被调用时加载。

## 执行语义

- 结果按评测器声明顺序返回，与并发完成顺序无关。
- 两个并发旋钮都有上界 8：`max_concurrency` 限定单个输入内并发的评测器，`max_samples` 限定
  `evaluate_many` 中同时运行的输入。一次批处理的 provider 并发不超过两者之积。
- 一次调用共享一个 provider 并发上限和一份成本预算。语义匹配等评测器的内部分批与其他评测器一起
  竞争同一个上限，因此嵌套不会放大并发；`evaluate_many` 的多个样本也共用同一份预算，而不是每个
  样本各算一次。
- `max_attempts` 约束**单次 Judge 调用**的 provider 重试（上限 20）；执行器不会重试已经产生 Judge
  调用的失败，因此不会出现重试次数相乘。多步评测器（如答案正确性、语义匹配分批）一次评测会发起多次
  Judge 调用，总请求数上限是调用次数乘以 `max_attempts`，预算在评测器结束后结算。
  已知费用按 `JudgeCallRecord.provenance.attempts` 汇总，包括输出校验失败但返回 usage 的尝试；
  `JudgeCallRecord.usage` 只表示最终成功响应，不能重复累加。设置预算后，未知或未定价成本会阻止
  后续样本和指标启动，保留已完成记录；这不是对在飞请求或多步评测器的硬费用上限。
- OpenAI 适配器关闭了 SDK 自带重试（`max_retries=0`），超时预算只由本包的重试策略消耗。
- `retry_backoff_seconds` 同时用于 Judge 重试的初始退避与执行器层重试。
- 截止时间与取消是协作式的，在批次前后与**每次 Judge 调用前**检查；取消或超时会把对应记录标记为
  `cancelled`/`failed`，已完成的记录保留；同时包含已完成与未完成指标时，整体状态为 `partial`。
  已经在飞的 provider 调用不会被强制中断，需要调用方在 transport 侧设置请求超时。
- `BatchingOptions` 默认每批最多 256 项、512,000 字节的 UTF-8 JSON payload。图忠实性、检索上下文、
  实体/证据覆盖和答案 NLI 按项分批；语义匹配同时对候选与参考分窗，全局索引始终保留。
  共享原文不会静默截断；答案分解和全局正确性分类保留整体语义，不机械拆段。单项加共享证据或整体任务
  超限时返回 `evaluation_payload_too_large`，保留已经发生的调用记录，不输出伪完整分数。
  字节限制不是模型 token 限制；系统提示、输出 schema 与输出长度还需 provider 侧配置。
- 记录级失败是数据而不是异常：输入不可物化、provider 失败、评测器返回非法值都会落到具体记录上；
  评测器抛出的 `KeyboardInterrupt`/`SystemExit` 之外的所有异常都转成失败记录，不会丢掉同批次的其他结果。
- 通过引擎执行时，评测器与 Judge 实现会被不同线程并发调用，必须是无共享可变状态的实现。

## 评分协议

- 语义匹配的每个候选/参考窗口返回所有可行配对，保留同一项的备选；没有匹配的 reference 才返回唯一 null。
  所有窗口返回的配对统一进行一对一分配，窗口内不提前匹配。默认 `matching_strategy="max_weight"`
  保留最大总权重目标；显式选 `"max_cardinality"` 才优先最大匹配数量，再最大权重，策略进入实现摘要。
  最优性仅覆盖 Judge 实际返回的配对，不保证模型穷尽真实语义关系。双侧分窗可能增加请求次数，
  歧义密集时输出仍可能超过模型限制，自定义 Judge/prompt 必须保留窗口内的全局索引与备选配对。
- Context entity recall 先固定实体清单，再校验覆盖。调用方传入 `reference_entities` 可以提供确定分母；
  未传时先独立抽取清单，该调用不读取检索上下文。覆盖阶段不得遗漏、改名或重排索引，空清单为
  `not_applicable`，不是满分。模型抽取本身仍可能漏实体，不能视为人工真值。
- Schema validity 只校验本包声明的基本结构：类型、必填主键、同类型复合主键唯一性以及真实边端点。
  完整数据库属性类型、非法属性与 edge sort keys 不在当前输入契约内，不应将满分解释为数据库写入保证。
- 答案的原子主张和实体文本保存在 findings 的 `evidence.description`；超过 2,000 字符时明确截断，避免
  仅留下无法从原始字符串还原的动态编号。图证据预览与组合 Finding 消息也遵守持久化字段的长度上限；
  完整模型输出仍由调用方负责持久化，输入证据本身不截断。
- 多 reference 聚合、重复 claim 权重和 relevant-context noise 模式的边界见使用指南，不能把这些指标
  直接解读为覆盖所有正确答案或所有噪声条件的完整质量结论。

## 扩展应该放在哪里

- 新增指标：实现 `Evaluator` 协议（或继承 `JudgedEvaluatorLifecycle`），在对应 `integrations/` 下注册
  输入 schema 与物化逻辑，并补齐行为测试。
- 接入新模型：实现 `Judge.judge`，或直接用 `openai_judge` 适配 OpenAI 兼容端点；用订阅额度时可用 `ClaudeCodeJudge`（`claude -p`）或 `CodexAppServerJudge`（`codex app-server`），三者共享 `AttemptLoopJudge` 的重试、退避与截止时间逻辑。订阅类 Judge 只报告 token、不报告费用，因此 `budget_usd` 不适用。
- 新增数据形态：在 `samples.py` 增加构造 helper，保持 evaluator 面向 artifact 契约不变。
- 持久化、报告、CLI 和产品字段映射：留在调用方或 `hugegraph-llm`，通过结构化结果衔接。

## 兼容与验证约定

- 基础安装只依赖 Pydantic；`networkx`、`rouge-score`、`jieba`、`openai` 全部是可选 extra。
- 独立安装验证在仓库工作区之外构建 wheel/sdist，再在干净 venv 中安装并运行完整测试；基础环境跑通
  可跳过的用例，安装 extras 后覆盖全部用例。
- 指标清单与用法以 [README](../../hugegraph-llm-sdk/eval/README.md) 为准；`examples/all_metrics.py` 一次跑通
  全部指标，CI 在安装 extras 的 wheel 环境里执行它。
- 导入隔离测试断言 `import hugegraph_llm_eval` 不加载应用与厂商模块。
- 评测指令中的示例必须保持领域中立，不得沉淀具体业务场景或内部评分文档引用。
