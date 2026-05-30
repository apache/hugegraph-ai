# Implementation Plan: Migrate .env Configuration to YAML with OmegaConf

- [x] 1. **Research & Preparation** `[Priority: High]`

  - [x] 1.1. Search codebase for all `update_env()`, `generate_env()`, `check_env()` call sites to ensure no missed migration targets. `(Related: E3, E12)`
  - [x] 1.2. Verify OmegaConf package availability: check PyPI version and Python 3.10 compatibility. `(Related: U1)`

- [x] 2. **Add OmegaConf Dependency** `[Priority: High]`

  - [x] 2.1. Add `"omegaconf~=2.3"` to `hugegraph-llm/pyproject.toml` `dependencies`. `(Related: U1)`
  - [x] 2.2. Add `"omegaconf~=2.3"` to root `pyproject.toml` `constraint-dependencies`. `(Related: U1)`
  - [x] 2.3. Run `uv sync` to install OmegaConf, verify import. `(Related: U1)` `(Depends on: 2.1, 2.2)`

- [x] 3. **Refactor BaseConfig Core** `[Priority: High]`

  - [x] 3.1. Create `ConfigManager` singleton class in `base_config.py` with `load()`, `save()`, `get_section()`, `update_section()`, `reload()`, `_migrate_from_env()`, `get_section_with_env_override()` methods. `(Related: U1, U2, U5, E1, E2, E7)`
  - [x] 3.2. Implement `_start_file_watcher()` / `_stop_file_watcher()` background polling thread in `ConfigManager` (using `os.path.getmtime()`). `(Related: E5, E6, E8)`
  - [x] 3.3. Refactor `BaseConfig`: switch from `BaseSettings` to `BaseModel`, add `_config_section` class attribute, rewrite `__init__` to load config from ConfigManager. `(Related: U3, U4)`
  - [x] 3.4. Implement `update_config()`, `generate_yaml()`, `check_config()` in `BaseConfig`, keep old methods (`update_env()`, etc.) as delegation stubs. `(Related: E3, E4)`
  - [x] 3.5. Fix PR #277 legacy issues: KeyError protection (ensure section key exists before access), fix comment typos. `(Related: U12)`
  - [x] 3.6. **New (not in original plan)**: Implement `_flat_to_nested()` / `_nested_to_flat()` bidirectional conversion utilities, supporting flat pydantic field names ↔ nested YAML structure.

- [x] 4. **Update Config Subclasses** `[Priority: High]` `(Depends on: 3.3)`

  - [x] 4.1. `LLMConfig`: add `_config_section = "llm"` and `_flat_to_nested_mapping` (42 dot-notation path mappings). Add `_env_var_map` for custom env var name mapping. Remove `os.environ.get()` defaults. `(Related: U3)`
  - [x] 4.2. `HugeGraphConfig`: add `_config_section = "hugegraph"` and `_flat_to_nested_mapping` (12 mappings: graph.*, query.*, vector.*, rerank.*). `(Related: U3)`
  - [x] 4.3. `AdminConfig`: add `_config_section = "admin"`, `_flat_to_nested_mapping` (3 mappings: login.*), add new `config_reload_interval: int = 5` field. `(Related: E7)`
  - [x] 4.4. `IndexConfig`: add `_config_section = "index"` and `_flat_to_nested_mapping` (7 mappings: qdrant.*, milvus.*). Remove `os.environ.get()` defaults. `(Related: U3)`

- [x] 5. **Update Config Initialization & Generation Tools** `[Priority: High]` `(Depends on: 3.1, 3.3, 4.*)`

  - [x] 5.1. Update `config/__init__.py`: initialize ConfigManager before config singletons, pass section→model_class mapping. `(Related: U3, E2)` `(Depends on: 3.1, 4.*)`
  - [x] 5.2. Update `config/generate.py`: `generate_env()` → `generate_yaml()` for all 4 config objects. `(Related: E11)` `(Depends on: 3.4)`
  - [x] 5.3. Update `config/models/base_prompt_config.py`: fix comments referencing `.env` → `config.yaml`. `(Related: U9)` `(Depends on: 3.*)`

- [x] 6. **Adapt Gradio UI Config Blocks** `[Priority: Medium]` `(Depends on: 3.4)`

  - [x] 6.1. Update `configs_block.py`: replace 6× `update_env()` calls with `update_config()`. `(Related: E12)` `(Depends on: 3.4)`
  - [x] 6.2. Update `configs_block.py`: remove direct `.env` reading via `dotenv_values()`, read from config objects instead (`llm_settings.openai_extract_api_key`). Remove unused `import os`. `(Related: E12)` `(Depends on: 6.1)`
  - [x] 6.3. Add exception handling and error logging for `update_config()` calls (PR #277 X4 protection). `(Related: X4)` `(Depends on: 6.1)`

- [x] 7. **Update .gitignore** `[Priority: Medium]` `(Depends on: 2.*)`

  - [x] 7.1. Add `config.yaml` and `config.yaml.bak` to root `.gitignore`. `(Related: U1)`

- [x] 8. **Update Documentation** `[Priority: Medium]` `(Depends on: 3.*, 4.*, 6.*)`

  - [x] 8.1. Update `hugegraph-llm/config.md`: full rewrite reflecting nested YAML section structure, env var priority (os.environ > config.yaml > pydantic defaults), hot-reload behavior, config reload interval documentation. `(Related: U9)`

- [x] 9. **Install Dependencies & Run Lint** `[Priority: Medium]` `(Depends on: 2.*, 7.*)`

  - [x] 9.1. Run `uv sync` to install OmegaConf. `(Depends on: 2.*)`
  - [x] 9.2. Run `ruff format --check` and `ruff check`, fix all lint errors. `(Related: U11, U12)`

- [x] 10. **Run Existing Tests (Regression Check)** `[Priority: High]` `(Depends on: 3.*, 4.*, 5.*, 6.*, 9.*)`

  - [x] 10.1. Run `pytest` — all 7 config tests pass. `(Related: U10)`
  - [x] 10.2. Manual verification: `from hugegraph_llm.config import ...` generates nested `config.yaml`. `(Related: E11)` `(Depends on: 10.1)`
  - [x] 10.3. Manual verification: `.env` exists → auto-migration to nested `config.yaml`, verified type conversion (int/float/bool/null preserved). `(Related: E9, E10)` `(Depends on: 10.1)`
  - [x] 10.4. Manual verification: env var override — `os.environ` overrides YAML values (e.g. `MAX_GRAPH_PATH=99`). `(Related: U5)`
  - [x] 10.5. Manual verification: OmegaConf dot-notation reads nested YAML — `cfg.llm.openai.chat.language_model`. `(Related: U1, U2)`

## Implementation Delta (vs. Original Plan)

Key differences between the actual implementation and the initial plan:

1. **Nested YAML structure** (original plan intended flat): User explicitly requested nested YAML (`ollama: extract_port: 11434` instead of `ollama_extract_port: 11434`). Implemented via `_flat_to_nested_mapping` ClassVar + `_flat_to_nested()` / `_nested_to_flat()` bidirectional conversion. Pydantic field names remain flat to maintain compatibility with 46 consumer files.

2. **OmegaConf.merge → OmegaConf.create**: `update_section()` uses `OmegaConf.create(nested_dict)` to fully replace the section, avoiding the bug where `OmegaConf.merge` preserves old flat keys alongside new nested structure.

3. **pydantic TypeAdapter** for env var type conversion: Avoids infinite recursion that occurred when creating temporary pydantic instances inside `get_section_with_env_override()`.
