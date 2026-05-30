# 实现计划: 将 .env 配置迁移到 YAML (使用 OmegaConf)

- [x] 1. **研究与准备** `[优先级: 高]`

  - [x] 1.1. 搜索代码库中 `update_env()`、`generate_env()`、`check_env()` 的所有调用点，确认无遗漏的迁移目标。 `(关联需求: E3, E12)`
  - [x] 1.2. 确认 OmegaConf 包可用性：检查 PyPI 版本及与 Python 3.10 的兼容性。 `(关联需求: U1)`

- [x] 2. **添加 OmegaConf 依赖** `[优先级: 高]`

  - [x] 2.1. 在 `hugegraph-llm/pyproject.toml` 的 `dependencies` 中添加 `"omegaconf~=2.3"`。 `(关联需求: U1)`
  - [x] 2.2. 在根 `pyproject.toml` 的 `constraint-dependencies` 中添加 `"omegaconf~=2.3"`。 `(关联需求: U1)`
  - [x] 2.3. 执行 `uv sync` 安装 OmegaConf，验证导入成功。 `(关联需求: U1)` `(依赖于: 2.1, 2.2)`

- [x] 3. **重构 BaseConfig 核心** `[优先级: 高]`

  - [x] 3.1. 在 `base_config.py` 中创建 `ConfigManager` 单例类，实现 `load()`、`save()`、`get_section()`、`update_section()`、`reload()`、`_migrate_from_env()`、`get_section_with_env_override()` 方法。 `(关联需求: U1, U2, U5, E1, E2, E7)`
  - [x] 3.2. 在 `ConfigManager` 中实现 `_start_file_watcher()` / `_stop_file_watcher()` 后台轮询线程（使用 `os.path.getmtime()`）。 `(关联需求: E5, E6, E8)`
  - [x] 3.3. 重构 `BaseConfig`：从 `BaseSettings` 改为 `BaseModel`，添加 `_config_section` 类属性，重写 `__init__` 从 ConfigManager 加载配置。 `(关联需求: U3, U4)`
  - [x] 3.4. 在 `BaseConfig` 中实现 `update_config()`、`generate_yaml()`、`check_config()` 方法，保留旧方法 (`update_env()` 等) 作为委托。 `(关联需求: E3, E4)`
  - [x] 3.5. 处理 PR #277 遗留问题：KeyError 保护（访问前确保 section key 存在）、注释拼写修正。 `(关联需求: U12)`
  - [x] 3.6. **新增 (未在原始计划中)**: 实现 `_flat_to_nested()` / `_nested_to_flat()` 双向转换工具函数，支持扁平 pydantic 字段名 ↔ 嵌套 YAML 结构。

- [x] 4. **更新各 Config 子类** `[优先级: 高]` `(依赖于: 3.3)`

  - [x] 4.1. `LLMConfig` 添加 `_config_section = "llm"` 和 `_flat_to_nested_mapping` (42 条 dot-notation path mapping)。添加 `_env_var_map` 支持自定义环境变量名映射。移除 `os.environ.get()` 默认值。 `(关联需求: U3)`
  - [x] 4.2. `HugeGraphConfig` 添加 `_config_section = "hugegraph"` 和 `_flat_to_nested_mapping` (12 条 mapping: graph.*, query.*, vector.*, rerank.*)。 `(关联需求: U3)`
  - [x] 4.3. `AdminConfig` 添加 `_config_section = "admin"`，`_flat_to_nested_mapping` (3 条 mapping: login.*)，新增 `config_reload_interval: int = 5` 字段。 `(关联需求: E7)`
  - [x] 4.4. `IndexConfig` 添加 `_config_section = "index"` 和 `_flat_to_nested_mapping` (7 条 mapping: qdrant.*, milvus.*)。移除 `os.environ.get()` 默认值。 `(关联需求: U3)`

- [x] 5. **更新配置初始化与生成工具** `[优先级: 高]` `(依赖于: 3.1, 3.3, 4.*)`

  - [x] 5.1. 更新 `config/__init__.py`：ConfigManager 在 config 单例之前初始化，传入 section→model_class 映射。 `(关联需求: U3, E2)` `(依赖于: 3.1, 4.*)`
  - [x] 5.2. 更新 `config/generate.py`：`generate_env()` → `generate_yaml()` 全部 4 个 config 对象。 `(关联需求: E11)` `(依赖于: 3.4)`
  - [x] 5.3. 更新 `config/models/base_prompt_config.py`：修正注释中 `.env` 引用为 `config.yaml`。 `(关联需求: U9)` `(依赖于: 3.*)`

- [x] 6. **适配 Gradio UI 配置块** `[优先级: 中]` `(依赖于: 3.4)`

  - [x] 6.1. 更新 `configs_block.py`：6 处 `update_env()` 调用替换为 `update_config()`。 `(关联需求: E12)` `(依赖于: 3.4)`
  - [x] 6.2. 更新 `configs_block.py`：移除 `dotenv_values()` 直接读取 `.env` 的逻辑，改为从 config 对象读取 (`llm_settings.openai_extract_api_key`)。移除未使用的 `import os`。 `(关联需求: E12)` `(依赖于: 6.1)`
  - [x] 6.3. 为 `update_config()` 调用添加异常捕获与错误日志（PR #277 X4 保护）。 `(关联需求: X4)` `(依赖于: 6.1)`

- [x] 7. **更新 .gitignore** `[优先级: 中]` `(依赖于: 2.*)`

  - [x] 7.1. 在根 `.gitignore` 中添加 `config.yaml` 和 `config.yaml.bak`。 `(关联需求: U1)`

- [x] 8. **更新文档** `[优先级: 中]` `(依赖于: 3.*, 4.*, 6.*)`

  - [x] 8.1. 更新 `hugegraph-llm/config.md`：全面重写，反映嵌套 YAML section 结构、环境变量优先级 (os.environ > config.yaml > pydantic defaults)、热加载行为、配置 reload interval 说明。 `(关联需求: U9)`

- [x] 9. **安装依赖并运行 Lint 检查** `[优先级: 中]` `(依赖于: 2.*, 7.*)`

  - [x] 9.1. 执行 `uv sync` 安装 OmegaConf。 `(依赖于: 2.*)`
  - [x] 9.2. 执行 `ruff format --check` 和 `ruff check`，修复所有 lint 错误。 `(关联需求: U11, U12)`

- [x] 10. **运行现有测试确保无回归** `[优先级: 高]` `(依赖于: 3.*, 4.*, 5.*, 6.*, 9.*)`

  - [x] 10.1. 运行 `pytest` 确认所有测试通过 (7 个 config 测试全部通过)。 `(关联需求: U10)`
  - [x] 10.2. 手动验证嵌套 YAML 生成：`from hugegraph_llm.config import ...` 生成嵌套结构 `config.yaml`。 `(关联需求: E11)` `(依赖于: 10.1)`
  - [x] 10.3. 手动验证 `.env` 迁移流程：`.env` 存在时自动迁移到嵌套 `config.yaml`，已验证类型转换（int/float/bool/null 保留正确类型）。 `(关联需求: E9, E10)` `(依赖于: 10.1)`
  - [x] 10.4. 手动验证环境变量覆盖：`os.environ` 覆盖 YAML 值（如 `MAX_GRAPH_PATH=99`）。 `(关联需求: U5)`
  - [x] 10.5. 手动验证 OmegaConf dot-notation 读取嵌套 YAML：`cfg.llm.openai.chat.language_model`。 `(关联需求: U1, U2)`

## 实现差异说明

以下为实际实现与最初计划的差异：

1. **嵌套 YAML 结构**（原计划保持扁平）：用户明确要求嵌套 YAML（`ollama: extract_port: 11434` 而非 `ollama_extract_port: 11434`）。通过 `_flat_to_nested_mapping` ClassVar + `_flat_to_nested()` / `_nested_to_flat()` 双向转换实现，pydantic 字段名保持扁平以兼容 46 个 consumer 文件。

2. **OmegaConf.merge → OmegaConf.create**：`update_section()` 中使用 `OmegaConf.create(nested_dict)` 直接替换整个 section，避免 `OmegaConf.merge` 导致旧扁平 key 与新嵌套结构并存的问题。

3. **pydantic TypeAdapter** 用于环境变量类型转换：避免在 `get_section_with_env_override` 中创建临时 pydantic 实例导致的无限递归。
