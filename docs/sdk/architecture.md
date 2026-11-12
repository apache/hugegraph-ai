# HugeGraph-LLM SDK 架构与扩展边界

SDK 面向独立 Python 项目提供图 schema 设计、校验和属性图抽取能力。接入示例与参数说明见
[使用指南](../../hugegraph-llm-sdk/README.md)；本文说明维护和扩展代码时应保留的边界。

## 包与模块职责

`hugegraph-llm-sdk/` 与 `hugegraph-llm/` 在仓库根目录平级。旧应用通过兼容层复用 SDK，
外部项目直接调用 SDK；图规则和模型传输实现只维护一份。

评测能力位于 `graphrag/eval/`：抽取、检索与答案的评分规则、Judge 协议和执行语义都只在该包内维护。
应用侧的评测流程、持久化与报告渲染留在 `hugegraph-llm`，通过该包公开的契约与评测器接入，不再复制评分实现。

| 位置 | 职责 |
| --- | --- |
| SDK `schema.py` | 生成 schema 草案，校验结构、声明及引用；保留问题供业务修改 |
| SDK `api.py` | 校验调用参数，创建每块模型，组织执行并汇总有序结果 |
| SDK `extraction_runtime/review.py` | 调度单块与批量执行，管理审阅、修复预算和块状态 |
| SDK `extraction_runtime/property_graph.py` | 实现 `PropertyGraphBundle`，处理属性图解析、类型、ID 和图约束 |
| SDK `models.py` / `prompts.py` | 定义模型协议、函数与线程适配、可注入的阶段提示词 |
| SDK `providers/` | 按需加载 OpenAI、Ollama、LiteLLM 传输适配器 |
| 旧应用 `operators/llm_op/`、`extraction_runtime/`、`models/llms/` | 适配旧入口参数、默认策略和模型类，委托 SDK 执行业务 |
| 旧应用 UI、HTTP、配置与输入层 | 处理组件、消息、表单保存、配置读取、文件解析和分块 |

SDK 的基础依赖限定为标准库和 Pydantic。模型、schema、prompt 与选项通过参数传入；核心不得
反向导入应用配置、UI、图客户端或日志初始化，也不读写应用配置文件。厂商依赖仅在使用对应适配器时加载。

## 扩展应该放在哪里

- 接入已有模型：实现 `generate(prompt=...)` 或 `agenerate(prompt=...)`，也可使用 `FunctionModel`。
- 调整阶段指令：注入设计 prompt 或 `GraphPrompts`，避免修改全局配置。
- 添加业务约束：传入 validators；基础校验先执行，业务问题参与修复，修复后重新校验。
- 替换处理步骤：扩展 `PropertyGraphBundle`，通过 `run_chunk` / `run_chunks` 或异步入口运行。
- 增加文件格式、结果存储或应用交互：放在调用方或旧应用中，通过文本输入和结构化结果连接 SDK。

## 执行与资源约定

抽取前先验证参数和 schema；校验不修改输入，也不补默认字段。一个字符串是一块，列表保留调用方的分块。
块级失败作为结果保留，不丢弃其他块；汇总只按输入顺序拼接 `final` / `validated` 图，不进行跨块消歧。
`final` 表示审阅通过；`validated` 表示关闭审阅后通过本地校验，两者不能混为同一种保障。

直接传入的模型由调用方管理生命周期。并发调用使用 `model_factory` 为每块创建独立实例；SDK 按
`max_workers` 分组执行，一组停止并释放工厂资源后再开始下一组，以限制同时打开的客户端数量。
同一块的抽取、审阅与修复复用该块模型，较慢的块会延迟下一组启动。

原生异步取消向上传播并清理资源。`ThreadedModel` 无法强制中断同步调用：取消时异步等待已提交的工作结束，
再传播取消和关闭工厂资源，避免关闭仍被线程使用的客户端。调用方应配置请求超时，并考虑线程池排队时间。

## 兼容与验证约定

旧入口通过适配层保留 HTTP 字段、审阅开关、并发默认值与 UI 持久化行为；SDK 的默认策略不能自动覆盖旧行为。
新增共享能力时，分别验证独立 SDK 合同和旧入口适配，避免只用 mock 绕过真实核心。

独立安装验证应在仓库工作区之外构建并安装 wheel，覆盖支持的 Python 版本；基础环境不安装应用和厂商依赖，
厂商适配器另行验证。固定响应的 HTTP fixture 用于验证传输与集成，真实模型效果需要单独评估。
