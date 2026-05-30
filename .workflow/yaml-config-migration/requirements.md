# Requirements: Migrate .env Configuration to YAML with OmegaConf

## 1. Introduction

The hugegraph-llm project currently manages user configuration (graph server connections, LLM provider keys/models, vector index parameters, etc.) via a flat `.env` file using `pydantic-settings` + `python-dotenv`. See [`config.md`](../../hugegraph-llm/config.md).

**Pain Points**:
- Flat `.env` lacks structure — 60+ configuration items are hard to browse and maintain
- All values are strings, losing type information
- No file-change detection / auto-reload — users must restart the application after editing the config file
- Modifying configuration requires `setattr` + `update_env()` (two steps), unintuitive API

**Goal**: Replace `.env` with a single structured YAML file (`config.yaml`) managed by OmegaConf, keep the existing Python API compatible, and **support runtime auto-reload when the config file is externally modified**.

Related: Issue [#234](https://github.com/apache/hugegraph-ai/issues/234) | Prior PR [#277](https://github.com/apache/hugegraph-ai/pull/277) (outdated / has merge conflicts) | Config doc [`config.md`](../../hugegraph-llm/config.md)

### PR #277 Review Legacy Issues

| Source | Issue | Covered In |
|--------|-------|------------|
| Copilot | Possible KeyError when `yaml_config[current_class_name]` is not initialized | Ensure key exists before section access |
| Copilot | Typo in comment: `'onfig'` → `'config'` | Code quality |
| imbajin | Missing EOF newline in `requirements.txt` | File formatting |
| CI | Pylint check failure | Code quality |

## 2. Requirements

### 2.1 Configuration Storage Migration from .env to YAML

- **User Story**: As a **hugegraph-llm operator/developer**, I want **all application configuration stored in a structured `config.yaml` file**, so that **it is easier to read, edit, and version-control**.

- **Acceptance Criteria (EARS format)**:
  - **U1**: The **`config.yaml`** shall **use OmegaConf for read/write, with top-level sections organized by config category: `llm`, `hugegraph`, `admin`, `index`**.
  - **U2**: The **field values in YAML** shall **preserve correct original types (int, float, bool, null, string)**.
  - **E1**: WHEN **the application first starts and `config.yaml` does not exist but `.env` exists**, the **system** shall **automatically read `.env` data, match fields by name to the corresponding section, convert types via pydantic validation, and write to `config.yaml`**.
  - **E2**: WHEN **the application first starts and neither file exists**, the **system** shall **generate `config.yaml` using pydantic model default values**.
  - **E3**: WHEN **the user modifies configuration in the Gradio UI or API and clicks "Apply"**, the **system** shall **persist changes to `config.yaml`**.

### 2.2 Maintain Existing Python Config API Compatibility

- **User Story**: As a **developer importing `hugegraph_llm.config`**, I want **attribute access like `llm_settings.language` and `huge_settings.graph_url` to remain unchanged**, so that **45+ consumer files require no modification**.

- **Acceptance Criteria (EARS format)**:
  - **U3**: The **`llm_settings`, `huge_settings`, `admin_settings`, `index_settings` singleton objects** shall **maintain the same attribute read/write style as before the refactor**.
  - **U4**: The **pydantic model classes (`LLMConfig`, `HugeGraphConfig`, etc.)** shall **continue to define field types and default values, serving as the config schema and validation layer**.
  - **E4**: WHEN **`update_config()` (replacing the old `update_env()`) is called**, the **system** shall **write current pydantic model values back to OmegaConf and persist to disk**.

### 2.3 Maintain Environment Variable Override Support

- **User Story**: As an **operator using container/K8s deployment**, I want **sensitive information injected via environment variables (e.g. `OPENAI_API_KEY`) to override values in `config.yaml`**, so that **secrets are managed securely following 12-factor app best practices**.

- **Acceptance Criteria (EARS format)**:
  - **U5**: The **config loading priority** shall **be `environment variables (os.environ) > config.yaml > pydantic defaults`, with environment variables having the highest priority**.
  - **U6**: The **OpenAI config fields (`openai_*_api_key`, `openai_*_api_base`)** shall **be overridden by corresponding environment variables (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_EMBEDDING_BASE_URL`)**.
  - **U7**: The **Cohere config field (`cohere_base_url`)** shall **be overridden by the `CO_API_URL` environment variable**.
  - **U8**: The **vector database config (Qdrant/Milvus connection parameters)** shall **be overridden by corresponding environment variables**.

### 2.4 Runtime Configuration Hot-Reload

- **User Story**: As an **operator directly editing `config.yaml`**, I want **a running application to automatically detect and load new configuration after I modify `config.yaml`**, so that **config changes take effect without restarting the application**.

- **Acceptance Criteria (EARS format)**:
  - **E5**: WHEN **the `config.yaml` file is externally modified (e.g. manually edited by user)**, the **system** shall **detect the change according to the `config_reload_interval` field in the `admin` section of `config.yaml` (default 5 seconds)**.
  - **E6**: WHEN **a file change is detected**, the **system** shall **reload `config.yaml`, sync new values to the corresponding pydantic singleton objects, and log the event**.
  - **E7**: The **`admin` section** shall **include a `config_reload_interval: int` field (default 5, unit: seconds), controlling the file change detection polling interval**.
  - **E8**: WHEN **`config_reload_interval` is set to 0 or negative**, the **system** shall **disable hot-reload detection and log the event**.
  - **X1**: IF **the changed `config.yaml` contains invalid values (type errors, missing required fields, etc.)**, THEN the **system** shall **log an error and retain the current in-memory valid configuration without interrupting service**.
  - **X2**: IF **the `config.yaml` file does not exist or is deleted during loading**, THEN the **system** shall **fall back to pydantic model defaults and log a warning**.

### 2.5 Legacy .env Compatibility and Smooth Migration

- **User Story**: As a **user upgrading from an older version**, I want **my existing `.env` to be automatically migrated to `config.yaml`**, so that **the upgrade process requires no manual reconfiguration**.

- **Acceptance Criteria (EARS format)**:
  - **E9**: WHEN **`.env` exists and `config.yaml` does not exist**, the **system** shall **match all key-value pairs from `.env` (converted to lowercase keys) against each pydantic model's field names, allocating them to the correct YAML section**.
  - **E10**: WHEN **migration completes**, the **system** shall **keep the original `.env` file untouched (do not delete), serving as a backup**.
  - **X3**: IF **a field in `.env` cannot be matched to any known pydantic model field**, THEN the **system** shall **skip that field and output a warning log, without blocking startup or migration**.

### 2.6 CLI Config Generation Tool Update

- **User Story**: As a **developer**, I want **`python -m hugegraph_llm.config.generate -U` to generate `config.yaml`**, so that **I can quickly initialize configuration**.

- **Acceptance Criteria (EARS format)**:
  - **E11**: WHEN **`python -m hugegraph_llm.config.generate -U` is executed**, the **system** shall **generate `config.yaml` with all default values, and simultaneously generate/update `config_prompt.yaml`**.

### 2.7 Gradio UI Config Block Adaptation

- **User Story**: As a **user configuring the system via Gradio Web UI**, I want **all config modifications to still take effect and persist through the UI**, so that **the user experience remains unchanged**.

- **Acceptance Criteria (EARS format)**:
  - **E12**: WHEN **the user clicks the "Apply Configuration" button in the Gradio UI**, the **system** shall **write changes to the pydantic model and call `update_config()` to persist to YAML**.
  - **X4**: IF **the `update_config()` call fails**, THEN the **system** shall **catch the exception and log an error, without throwing an unhandled exception to the user**.

### 2.8 Documentation Update

- **User Story**: As a **developer reading `config.md`**, I want **the documentation to reflect the new YAML configuration approach and runtime hot-reload behavior**, so that **I can correctly understand and use the config system**.

- **Acceptance Criteria (EARS format)**:
  - **U9**: The **`hugegraph-llm/config.md`** shall **update all `.env` references to `config.yaml`, and add documentation of hot-reload behavior**.

### 2.9 Non-Functional Requirements

- **U10**: The **existing tests (263 unit/integration tests)** shall **all pass with no regressions**.
- **U11**: The **code** shall **pass `ruff format --check` and `ruff check` with no lint errors**.
- **U12**: The **3 legacy PR #277 review issues** shall **all be fixed in the new implementation**.
