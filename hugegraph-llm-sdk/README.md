# HugeGraph-LLM SDK

面向独立 Python 项目的 HugeGraph-LLM 能力调用接口，发行名为 `hugegraph-llm-sdk`，导入名为 `hugegraph_llm_sdk`。当前提供图 schema 设计、校验、属性图抽取、审阅和有限修复；传入自己的模型即可使用，不需要图数据库、Gradio 或 HTTP 服务。

SDK 的命名为后续更多可组合的 LLM 能力保留空间，当前实现范围仍限于上述图设计与抽取流程。它沿用 HugeGraph 属性图规则，基础安装只依赖 Pydantic。模型厂商适配器按需安装；SDK 不会加载旧应用配置、读写 `.env` / YAML、创建日志文件或配置宿主程序的日志。

## 目录与包边界

本目录保留抽取 SDK 的 `src/hugegraph_llm_sdk/`，并在 [eval/](eval/README.md)
存放独立评测 SDK。两者分别拥有 `pyproject.toml`，由仓库根 workspace 管理；
`eval/` 不属于 `hugegraph_llm_sdk` 命名空间，也不随本包的 wheel 或源码包分发。
评测包的发行名是 `hugegraph-llm-eval`，导入名是 `hugegraph_llm_eval`，可单独安装。
抽取 SDK 或应用需要评测时，通过评测包的公开输入和结果契约按需接入；本次目录调整
不增加隐式依赖，也不改变抽取或评测 API。

## 安装到另一个项目

此 SDK 随当前源码提供，尚未通过本次变更发布到公共包仓库。请使用仓库路径或构建的 wheel，勿假定公共索引已有此版本。

```bash
# 在自己的 Python 项目目录中执行；路径替换为实际 checkout
uv add --editable /absolute/path/hugegraph-ai/hugegraph-llm-sdk

# 需要现成 OpenAI 适配器时，显式安装对应 extra
uv add --editable /absolute/path/hugegraph-ai/hugegraph-llm-sdk --extra openai
```

也可以构建 wheel 后安装到外部项目：

```bash
uv build --no-sources /absolute/path/hugegraph-ai/hugegraph-llm-sdk --out-dir /tmp/llm-sdk-dist
uv add /tmp/llm-sdk-dist/hugegraph_llm_sdk-1.8.0-py3-none-any.whl
```

SDK 与应用均支持 Python 3.12–3.14，并通过独立安装矩阵验证。修改 editable 安装指向的 SDK 源码后，外部项目下次运行会使用这些改动，无需复制源码或重新安装 wheel。

## 最小接入

```python
from hugegraph_llm_sdk import (
    FunctionModel,
    design_schema,
    extract_graph,
    validate_schema,
)

model = FunctionModel(generate=lambda prompt: my_agent_model.invoke(prompt).content)

draft = design_schema(
    ["Alice works for Acme."],
    questions=["Which company does each person work for?"],
    model=model,
)
if draft.issues:
    # 把问题展示给业务方，修改 draft.schema 后再次校验
    raise ValueError(draft.issues)

schema = draft.schema
assert not validate_schema(schema)
result = extract_graph("Alice works for Acme.", schema=schema, model=model)

for chunk in result.chunks:
    if chunk.status == "final":
        my_save(chunk.graph)
    else:
        my_record_issue(chunk.index, chunk.status, chunk.issues, chunk.reason)
```

`my_agent_model`、`my_save` 和 `my_record_issue` 属于调用方。无需继承旧应用的 `BaseLLM`；已有对象只要提供 `generate(prompt=...) -> str`，也可以直接作为 `model` 传入。

[basic.py](examples/basic.py) 是不需要凭据的完整示例，使用固定模型响应演示“设计 → 修改 schema → 校验 → 抽取”。它用于检查接入流程，不衡量真实模型质量。

## 输入、结果和默认行为

| 接口 | 行为 |
| --- | --- |
| `design_schema` / `adesign_schema` | 根据文本、业务问题和可选示例生成 `SchemaDraft(schema, issues)`；合法 JSON 中的 schema 问题作为 issues 返回供修改 |
| `validate_schema` | 返回结构化 issues，不修改输入，不补主键、类型或 nullable 默认值 |
| `extract_graph` / `aextract_graph` | 抽取前校验 schema；返回 `ExtractionResult(status, chunks, graph)` |

校验范围由 schema 中实际声明的信息决定：省略 `propertykeys` 时，不检查全局属性声明引用；省略标签的 `properties` 时，不限制该标签的属性集合，而显式 `properties: []` 表示不允许任何属性。需要严格属性白名单和类型校验时，请完整声明 `properties` 和 `propertykeys`；`validate_schema` 不会替调用方补全这些声明。

边标签的 `sort_keys` 不能同时属于 `nullable_keys`。显式声明 `frequency` 时，`SINGLE` / `DEFAULT` 不允许排序键，`MULTIPLE` 必须声明非空排序键；省略 `frequency` 时不推断或补写默认值。

- 一个字符串是一个文本单元，列表中的每个字符串是一块；SDK 不隐式重新切分。PDF、DOCX、网页读取和分块由调用方负责。
- 默认启用审阅修复，最多 2 次审阅、1 次修复；默认并发为 1。调用次数统计不包括模型 SDK 自身的网络重试。
- 默认流程的块状态为 `final`、`candidate`、`blocked` 或 `failed`。只有 `final` 汇总到 `result.graph`；预算不足的 candidate 仍保留以便业务方处理。
- 显式传 `review=False` 时只抽取和本地校验，不调用审阅或修复模型；通过的状态为 `validated`，也会汇总到 `result.graph`。
- 总体 `status` 为 `succeeded`、`partial` 或 `failed`。模型或块级处理失败不会丢弃其他块的结果；调用方应检查状态，而非只检查是否抛出异常。
- 参数或 schema 无效时，在调用模型前报错。汇总图按输入顺序拼接完成块，不进行跨块实体消歧、去重或语义合并。
- SDK 不写库、不刷新索引、不保存任务；返回结果的保存和后续处理由调用方决定。

## 替换模型、prompt 和校验规则

现成适配器使用显式参数，不读取旧应用配置：

```python
from hugegraph_llm_sdk.providers.openai import OpenAIClient

model = OpenAIClient(
    api_key=my_api_key,
    api_base=my_api_base,
    model_name=my_model_name,
)
```

对应可选依赖为 `openai`、`ollama` 和 `litellm`；类分别是 `OpenAIClient`、`OllamaClient` 和 `LiteLLMClient`，均位于各自同名 provider 模块中。只导入使用的 provider。新适配器默认将模型截断作为错误；供应商仍可能施加上下文或输出限制。

直接传入的 `model` 由调用方管理生命周期，SDK 不会自动关闭它。OpenAI 和 Ollama 适配器提供 `close()` 释放同步客户端、`await aclose()` 释放异步及同步客户端；用完后由调用方选择对应方式清理。LiteLLM 适配器使用供应商共享连接池，不持有或关闭全局 transport。

抽取、审阅、修复 prompt 可以通过 `GraphPrompts(extract=..., review=..., repair=...)` 覆盖；未传的字段保留内置默认值。图设计使用 `design_schema(..., prompt=...)`，模板支持 `{raw_texts}`、`{query_examples}`、`{few_shot_schema}`。

自定义校验器接收 `(graph, schema, text)`，返回 `list[Issue]`。它在基础校验后运行，问题会进入修复循环；修复后的图会重新校验。参见可离线运行的 [customization.py](examples/customization.py)。

需要修改某个步骤时，可以扩展 `PropertyGraphBundle` 的 `extract / validate / review / repair` 方法，然后使用公共 `run_chunk` / `run_chunks`。对应异步方法为 `aextract / areview / arepair`，本地 `validate` 保持同步；异步运行入口是 `arun_chunk` / `arun_chunks`。这些类型和函数位于 `hugegraph_llm_sdk.extraction_runtime` 的 `property_graph` 与 `review` 模块。

```python
from hugegraph_llm_sdk.extraction_runtime.property_graph import PropertyGraphBundle
from hugegraph_llm_sdk.extraction_runtime.review import ChunkInput, ExtractionOptions, run_chunk


class ProjectBundle(PropertyGraphBundle):
    def validate(self, graph, chunk):
        issues = super().validate(graph, chunk)
        return issues + project_rules(graph, self.schema, chunk.text)


chunk = run_chunk(
    bundle=ProjectBundle(llm=model, schema=schema),
    chunk=ChunkInput(0, text),
    options=ExtractionOptions(max_workers=1),
)
```

## 异步与批量处理

原生异步项目传入实现 `agenerate(prompt=...)` 的模型，或 `FunctionModel(agenerate=async_function)`，然后调用 `adesign_schema` / `aextract_graph`。参见 [async_example.py](examples/async_example.py)。

只有同步模型时，显式使用 `ThreadedModel(sync_model)` 将模型调用放在线程中。调用任务收到取消后，适配器会异步等待已经提交到线程池的同步调用完成，再传播 `CancelledError`；工厂创建的模型随后才会清理。等待期间事件循环仍可运行，但同步调用不能被强制中断，取消返回可能延后；请在同步模型侧设置请求超时，并考虑线程池排队时间。直接传入的模型仍由调用方管理生命周期。

并发大于 1 时必须使用无参数 `model_factory`，每块返回独立模型实例：

```python
from hugegraph_llm_sdk import ExtractionOptions, extract_graph

result = extract_graph(
    chunks,
    schema=schema,
    model_factory=lambda: OpenAIClient(api_key=my_api_key, model_name=my_model_name),
    options=ExtractionOptions(max_workers=4),
)
```

`model` 和 `model_factory` 二选一；不要让工厂返回同一个有可变状态的客户端。返回的块结果始终按输入顺序排列。同一块的抽取、审阅和修复复用该块的模型实例。

SDK 负责清理 `model_factory` 创建的模型。输入按最多 `max_workers` 块一组执行，每组 worker 完成或停止后关闭该组模型，再创建下一组；未关闭的工厂模型数量因此不超过并发限制。较慢的块会延迟下一组启动。同步入口在批次调用线程执行模型提供的 `close()`，不保证与并发 worker 中的创建操作处于同一线程；异步入口优先等待 `aclose()`，只有 `close()` 时在线程中清理。取消时仍完成已创建模型的清理；若某个模型的关闭协程自身取消，会先尝试关闭同组其他模型，再传播取消。未提供关闭方法的自定义模型无需实现空方法。工厂本身是同步函数，构建时应避免阻塞网络 I/O。

## 与旧应用的关系

SDK 与应用在仓库根目录下平级：`hugegraph-llm-sdk/` 提供可独立安装的 Python 接口，`hugegraph-llm/` 提供 UI、HTTP 和应用工作流。依赖方向是应用调用 SDK；SDK 不依赖应用，也不需要安装整个仓库的依赖。

旧 UI 和 HTTP 的图设计／抽取入口复用 SDK，但保留原有参数、表单保存、配置文件和返回合同。旧 `/graph/extract` 仍通过显式 `review_options` 开启审阅，旧入口的默认并发也保持不变；它们不会自动采用新 SDK 的默认策略。

完整旧 HTTP 服务的启动仍属于 `hugegraph-llm` 应用；召回、写库、索引以及文件上传也继续由该应用负责。这些应用能力尚未作为本 SDK 的独立接口交付。

## 验证

CI 在仓库工作区之外构建并安装 wheel，分别验证 Python 3.12、3.13 和 3.14。基础环境运行隔离 smoke、离线示例和 SDK 测试；模型适配器另有安装 extras 的契约测试，网络请求在测试边界替换。

源码开发可使用根工作区已有的测试环境运行 SDK 测试。发布前仍需执行独立 wheel 验证，不能用源码路径注入代替安装验收。
