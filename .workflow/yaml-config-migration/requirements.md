# 需求文档: 将 .env 配置迁移到 YAML (使用 OmegaConf)

## 1. 介绍

当前 hugegraph-llm 项目的用户配置（图服务器连接、LLM 提供商密钥/模型、向量索引参数等）通过扁平的 `.env` 文件管理，底层使用 `pydantic-settings` + `python-dotenv`。详见 [`config.md`](../../hugegraph-llm/config.md)。

**痛点**:
- `.env` 扁平无结构，60+ 配置项难以浏览和维护
- 所有值均为字符串，类型信息丢失
- 没有文件变更自动感知/重载能力 —— 用户直接编辑配置文件后必须重启应用
- 修改配置需要 `setattr` + `update_env()` 两步操作，API 不直观

**目标**: 用单一结构化 YAML 文件 (`config.yaml`) 替代 `.env`，引入 OmegaConf 作为配置框架，保持现有 Python API 兼容，**并支持运行时检测外部文件变更后自动重载**。

关联: Issue [#234](https://github.com/apache/hugegraph-ai/issues/234) | 先行 PR [#277](https://github.com/apache/hugegraph-ai/pull/277)（已过期/存在冲突）| 配置文档 [`config.md`](../../hugegraph-llm/config.md)

### PR #277 Review 遗留问题

| 来源 | 问题 | 需在本需求中覆盖 |
|------|------|-----------------|
| Copilot | `yaml_config[current_class_name]` 未初始化时可能 KeyError | 访问 section 前确保 key 存在 |
| Copilot | 注释拼写错误 `'onfig'` → `'config'` | 代码质量 |
| imbajin | `requirements.txt` EOF 缺少换行 | 文件格式 |
| CI | Pylint 检查失败 | 代码质量 |

## 2. 需求列表

### 2.1 配置存储格式从 .env 迁移到 YAML

- **用户故事**: 作为一名 **hugegraph-llm 的运维/开发者**, 我希望 **所有应用配置存储在一个结构化的 `config.yaml` 文件中**, 以便 **更容易阅读、编辑和版本管理**。

- **验收标准 (EARS 格式)**:
  - **U1**: The **`config.yaml`** shall **使用 OmegaConf 进行读写，顶层按配置类别分为 `llm`、`hugegraph`、`admin`、`index` 四个 section**。
  - **U2**: The **YAML 中的字段值** shall **保留正确的原始类型（整数、浮点数、布尔值、null、字符串）**。
  - **E1**: WHEN **应用首次启动且 `config.yaml` 不存在但 `.env` 存在**, the **系统** shall **自动读取 `.env` 数据，按字段名匹配到对应 section，经 pydantic 校验转类型后写入 `config.yaml`**。
  - **E2**: WHEN **应用首次启动且两个文件都不存在**, the **系统** shall **使用 pydantic 模型的默认值生成 `config.yaml`**。
  - **E3**: WHEN **用户在 Gradio UI 或 API 中修改配置并点击"应用"**, the **系统** shall **将变更持久化到 `config.yaml`**。

### 2.2 保持现有 Python 配置 API 兼容

- **用户故事**: 作为一名 **导入 `hugegraph_llm.config` 的开发者**, 我希望 **`llm_settings.language`、`huge_settings.graph_url` 等属性访问方式不变**, 以便 **45+ 个消费文件无需修改**。

- **验收标准 (EARS 格式)**:
  - **U3**: The **`llm_settings`、`huge_settings`、`admin_settings`、`index_settings` 单例对象** shall **保持与重构前相同的属性读写方式**。
  - **U4**: The **pydantic 模型类 (`LLMConfig`、`HugeGraphConfig` 等)** shall **继续定义字段类型与默认值，作为配置的 schema 和校验层**。
  - **E4**: WHEN **调用 `update_config()`（替代原 `update_env()`）**, the **系统** shall **将当前 pydantic 模型值写回 OmegaConf 并保存到磁盘**。

### 2.3 保持环境变量覆盖支持

- **用户故事**: 作为一名 **使用容器/K8s 部署的运维人员**, 我希望 **通过环境变量注入的敏感信息（如 `OPENAI_API_KEY`）能够覆盖 `config.yaml` 中的值**, 以便 **安全地管理密钥并遵循 12-factor app 最佳实践**。

- **验收标准 (EARS 格式)**:
  - **U5**: The **配置加载优先级** shall **为 `环境变量 (os.environ) > config.yaml > pydantic 默认值`，环境变量具有最高优先级**。
  - **U6**: The **OpenAI 配置字段 (`openai_*_api_key`, `openai_*_api_base`)** shall **被对应的环境变量 (`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_EMBEDDING_BASE_URL`) 覆盖**。
  - **U7**: The **Cohere 配置字段 (`cohere_base_url`)** shall **被 `CO_API_URL` 环境变量覆盖**。
  - **U8**: The **向量数据库配置 (Qdrant/Milvus 连接参数)** shall **被对应环境变量覆盖**。

### 2.4 运行时配置热加载

- **用户故事**: 作为一名 **直接编辑 `config.yaml` 的运维人员**, 我希望 **修改 `config.yaml` 后运行中的应用能自动检测并加载新配置**, 以便 **无需重启应用即可让配置变更生效**。

- **验收标准 (EARS 格式)**:
  - **E5**: WHEN **`config.yaml` 文件在外部被修改（如用户手动编辑）**, the **系统** shall **根据 `config.yaml` 中 `admin` section 的 `config_reload_interval` 字段值（默认 5 秒）检测到变更**。
  - **E6**: WHEN **检测到文件变更**, the **系统** shall **重新加载 `config.yaml`，将新值同步到对应的 pydantic 单例对象，并记录日志**。
  - **E7**: The **`admin` section** shall **包含 `config_reload_interval: int` 字段（默认 5，单位秒），控制文件变更检测轮询间隔**。
  - **E8**: WHEN **`config_reload_interval` 设为 0 或负数**, the **系统** shall **禁用热加载检测并记录日志**。
  - **X1**: IF **变更后的 `config.yaml` 包含非法值（类型错误、必填字段缺失等）**, THEN the **系统** shall **记录错误日志并保留当前内存中的有效配置，不中断运行**。
  - **X2**: IF **`config.yaml` 文件在加载过程中不存在或被删除**, THEN the **系统** shall **回退到 pydantic 模型默认值并记录警告日志**。

### 2.5 旧版 .env 兼容与平滑迁移

- **用户故事**: 作为一名 **从旧版本升级的用户**, 我希望 **已有的 `.env` 能自动迁移为 `config.yaml`**, 以便 **升级过程无需手动重新配置**。

- **验收标准 (EARS 格式)**:
  - **E9**: WHEN **`.env` 存在而 `config.yaml` 不存在**, the **系统** shall **将 `.env` 中所有键值对（转为小写 key）与各 pydantic 模型的字段名匹配，分配到正确的 YAML section**。
  - **E10**: WHEN **迁移完成**, the **系统** shall **保留原有 `.env` 不动（不删除），作为备份**。
  - **X3**: IF **`.env` 中某字段无法匹配到任何已知 pydantic 模型字段**, THEN the **系统** shall **跳过该字段并输出警告日志，不阻断启动或迁移流程**。

### 2.6 CLI 配置生成工具更新

- **用户故事**: 作为一名 **开发者**, 我希望 **`python -m hugegraph_llm.config.generate -U` 能生成 `config.yaml`**, 以便 **快速初始化配置**。

- **验收标准 (EARS 格式)**:
  - **E11**: WHEN **执行 `python -m hugegraph_llm.config.generate -U`**, the **系统** shall **生成包含所有默认值的 `config.yaml`，并同时生成/更新 `config_prompt.yaml`**。

### 2.7 Gradio UI 配置块适配

- **用户故事**: 作为一名 **通过 Gradio Web UI 配置系统的用户**, 我希望 **所有配置修改仍然通过 UI 生效并持久化**, 以便 **使用体验不变**。

- **验收标准 (EARS 格式)**:
  - **E12**: WHEN **用户在 Gradio UI 中点击"Apply Configuration"按钮**, the **系统** shall **将修改写入 pydantic 模型并调用 `update_config()` 持久化到 YAML**。
  - **X4**: IF **`update_config()` 调用失败**, THEN the **系统** shall **捕获异常并记录错误日志，不向用户抛出未处理的异常**。

### 2.8 文档更新

- **用户故事**: 作为一名 **查阅 `config.md` 的开发者**, 我希望 **文档反映新的 YAML 配置方式和运行时热加载行为**, 以便 **正确理解和使用配置系统**。

- **验收标准 (EARS 格式)**:
  - **U9**: The **`hugegraph-llm/config.md`** shall **更新所有 `.env` 引用为 `config.yaml`，并新增热加载行为说明**。

### 2.9 非功能需求

- **U10**: The **现有测试 (263 个单元/集成)** shall **全部通过，无回归**。
- **U11**: The **代码** shall **通过 `ruff format --check` 和 `ruff check`，无 lint 错误**。
- **U12**: The **PR #277 的 3 个遗留 Review 问题** shall **在新实现中全部修复**。
