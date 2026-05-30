# HugeGraph LLM 配置选项 (详解)

本文档详细说明了 HugeGraph LLM 项目中所有的配置选项。配置分为以下几类：

1. **基础配置**：通过 `config.yaml` 文件管理（使用 OmegaConf）
2. **Prompt 配置**：通过 `config_prompt.yaml` 文件管理
3. **Docker 配置**：通过 Docker 和 Helm 配置文件管理
4. **项目配置**：通过 `pyproject.toml` 和 `JSON` 文件管理

## 目录

- [config.yaml 配置文件](#configyaml-配置文件)
  - [基础配置](#基础配置)
  - [OpenAI 配置](#openai-配置)
  - [Ollama 配置](#ollama-配置)
  - [LiteLLM 配置](#litellm-配置)
  - [重排序配置](#重排序配置)
  - [HugeGraph 数据库配置](#hugegraph-数据库配置)
  - [向量数据库配置](#向量数据库配置)
  - [管理员配置](#管理员配置)
- [配置优先级](#配置优先级)
- [运行时热加载](#运行时热加载)
- [配置使用示例](#配置使用示例)
- [配置文件位置](#配置文件位置)

## config.yaml 配置文件

`config.yaml` 文件位于当前工作目录（通常是 `hugegraph-llm/`）下，使用结构化 YAML 格式存储所有配置项。配置被分为四个顶层 section：`llm`、`hugegraph`、`admin`、`index`。

### 基础配置

```yaml
llm:
  language: EN                        # prompt语言，支持 EN（英文）和 CN（中文）
  chat_llm_type: openai               # 聊天 LLM 类型：openai/litellm/ollama/local
  extract_llm_type: openai            # 信息提取 LLM 类型
  text2gql_llm_type: openai           # 文本转 GQL LLM 类型
  embedding_type: openai              # 嵌入模型类型
  reranker_type: null                 # 重排序模型类型：cohere/siliconflow
  keyword_extract_type: llm           # 关键词提取模型类型：llm/textrank/hybrid
  window_size: 3                      # TextRank 滑窗大小 (范围: 1-10)
  hybrid_llm_weights: 0.5             # 混合模式中 LLM 结果的权重 (范围: 0.0-1.0)
```

### OpenAI 配置

```yaml
llm:
  openai_chat_api_base: https://api.openai.com/v1
  openai_chat_api_key: null           # 建议通过环境变量 OPENAI_API_KEY 设置
  openai_chat_language_model: gpt-4.1-mini
  openai_chat_tokens: 8192
  openai_extract_api_base: https://api.openai.com/v1
  openai_extract_api_key: null
  openai_extract_language_model: gpt-4.1-mini
  openai_extract_tokens: 256
  openai_text2gql_api_base: https://api.openai.com/v1
  openai_text2gql_api_key: null
  openai_text2gql_language_model: gpt-4.1-mini
  openai_text2gql_tokens: 4096
  openai_embedding_api_base: https://api.openai.com/v1
  openai_embedding_api_key: null
  openai_embedding_model: text-embedding-3-small
```

#### OpenAI 环境变量覆盖

| 环境变量 | 覆盖的配置字段 | 说明 |
|---------|--------------|------|
| `OPENAI_BASE_URL` | `openai_chat_api_base`, `openai_extract_api_base`, `openai_text2gql_api_base` | 通用 OpenAI API 基础 URL |
| `OPENAI_API_KEY` | `openai_chat_api_key`, `openai_extract_api_key`, `openai_text2gql_api_key` | 通用 OpenAI API 密钥 |
| `OPENAI_EMBEDDING_BASE_URL` | `openai_embedding_api_base` | OpenAI 嵌入 API 基础 URL |
| `OPENAI_EMBEDDING_API_KEY` | `openai_embedding_api_key` | OpenAI 嵌入 API 密钥 |

### Ollama 配置

```yaml
llm:
  ollama_chat_host: 127.0.0.1
  ollama_chat_port: 11434
  ollama_chat_language_model: null
  ollama_extract_host: 127.0.0.1
  ollama_extract_port: 11434
  ollama_extract_language_model: null
  ollama_text2gql_host: 127.0.0.1
  ollama_text2gql_port: 11434
  ollama_text2gql_language_model: null
  ollama_embedding_host: 127.0.0.1
  ollama_embedding_port: 11434
  ollama_embedding_model: null
```

### LiteLLM 配置

```yaml
llm:
  litellm_chat_api_key: null
  litellm_chat_api_base: null
  litellm_chat_language_model: openai/gpt-4.1-mini
  litellm_chat_tokens: 8192
  litellm_extract_api_key: null
  litellm_extract_api_base: null
  litellm_extract_language_model: openai/gpt-4.1-mini
  litellm_extract_tokens: 256
  litellm_text2gql_api_key: null
  litellm_text2gql_api_base: null
  litellm_text2gql_language_model: openai/gpt-4.1-mini
  litellm_text2gql_tokens: 4096
  litellm_embedding_api_key: null
  litellm_embedding_api_base: null
  litellm_embedding_model: openai/text-embedding-3-small
```

### 重排序配置

```yaml
llm:
  cohere_base_url: https://api.cohere.com/v1/rerank
  reranker_api_key: null
  reranker_model: null
```

#### 重排序环境变量覆盖

| 环境变量 | 覆盖的配置字段 | 说明 |
|---------|--------------|------|
| `CO_API_URL` | `cohere_base_url` | Cohere API URL |

### HugeGraph 数据库配置

```yaml
hugegraph:
  graph_url: 127.0.0.1:8080
  graph_name: hugegraph
  graph_user: admin
  graph_pwd: xxx
  graph_space: null
  limit_property: "False"             # 注意：这是字符串类型，不是布尔
  max_graph_path: 10
  max_graph_items: 30
  edge_limit_pre_label: 8
  vector_dis_threshold: 0.9
  topk_per_keyword: 1
  topk_return_results: 20
```

### 向量数据库配置

```yaml
index:
  qdrant_host: null
  qdrant_port: 6333
  qdrant_api_key: null
  milvus_host: null
  milvus_port: 19530
  milvus_user: ""
  milvus_password: ""
  cur_vector_index: Faiss
```

#### 向量数据库环境变量覆盖

| 环境变量 | 覆盖的配置字段 | 说明 |
|---------|--------------|------|
| `QDRANT_HOST` | `qdrant_host` | Qdrant 服务器主机 |
| `QDRANT_PORT` | `qdrant_port` | Qdrant 服务器端口 |
| `QDRANT_API_KEY` | `qdrant_api_key` | Qdrant API 密钥 |
| `MILVUS_HOST` | `milvus_host` | Milvus 服务器主机 |
| `MILVUS_PORT` | `milvus_port` | Milvus 服务器端口 |
| `MILVUS_USER` | `milvus_user` | Milvus 用户名 |
| `MILVUS_PASSWORD` | `milvus_password` | Milvus 密码 |
| `CUR_VECTOR_INDEX` | `cur_vector_index` | 当前向量索引类型 |

### 管理员配置

```yaml
admin:
  enable_login: "False"               # 注意：这是字符串类型，不是布尔
  user_token: "4321"
  admin_token: "xxxx"
  config_reload_interval: 5           # 热加载检测间隔（秒），0 或负数禁用
```

## 配置优先级

配置值按以下优先级加载（高到低）：

1. **环境变量 (`os.environ`)** — 最高优先级，适用于容器/K8s 部署注入敏感信息
2. **`config.yaml` 文件** — 持久化配置存储，通过 UI 或 CLI 修改后写入
3. **pydantic 模型默认值** — 代码中定义的 fallback 值

`.env` 文件（如存在）会在启动时被加载到 `os.environ` 中，因此 `.env` 中的值优先级高于 `config.yaml`。如需从旧版 `.env` 迁移，首次启动时会自动生成 `config.yaml` 并保留原 `.env` 作为备份。

## 运行时热加载

系统在后台运行文件监控线程，定期检查 `config.yaml` 是否被外部修改：

- **检测间隔**：由 `admin.config_reload_interval` 控制（默认 5 秒）
- **设为 0 或负数**：禁用热加载检测
- **检测到变更时**：自动重新加载 `config.yaml`，验证配置合法性，同步到内存中的配置对象
- **配置文件不合法时**：记录错误日志，**保留当前内存中的有效配置**，不中断运行
- **配置文件被删除时**：回退到 pydantic 模型默认值并记录警告

## 配置使用示例

### 1. 基础配置示例 (config.yaml)

```yaml
llm:
  language: EN
  chat_llm_type: openai
  extract_llm_type: openai
  text2gql_llm_type: openai
  embedding_type: openai
  openai_chat_api_key: your-openai-api-key
  openai_chat_language_model: gpt-4.1-mini
  openai_embedding_model: text-embedding-3-small

hugegraph:
  graph_url: 127.0.0.1:8080
  graph_name: hugegraph
  graph_user: admin
  graph_pwd: your-password
```

### 2. 使用 Ollama 的配置示例

```yaml
llm:
  chat_llm_type: ollama/local
  extract_llm_type: ollama/local
  text2gql_llm_type: ollama/local
  embedding_type: ollama/local
  ollama_chat_language_model: llama2
  ollama_extract_language_model: llama2
  ollama_text2gql_language_model: llama2
  ollama_embedding_model: nomic-embed-text
```

### 3. 代码中使用配置

```python
from hugegraph_llm.config import llm_settings, huge_settings

# 使用 LLM 配置
print(f"当前语言: {llm_settings.language}")
print(f"聊天模型类型: {llm_settings.chat_llm_type}")

# 使用图数据库配置
print(f"图数据库地址: {huge_settings.graph_url}")
print(f"数据库名称: {huge_settings.graph_name}")
```

或者直接导入配置类：

```python
from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.config.hugegraph_config import HugeGraphConfig

# 创建配置实例
llm_config = LLMConfig()
graph_config = HugeGraphConfig()

print(f"当前语言: {llm_config.language}")
print(f"聊天模型类型: {llm_config.chat_llm_type}")
print(f"图数据库地址: {graph_config.graph_url}")
print(f"数据库名称: {graph_config.graph_name}")
```

### 4. 生成配置文件

```bash
# 生成包含所有默认值的 config.yaml 和 config_prompt.yaml
python -m hugegraph_llm.config.generate -U
```

## 注意事项

1. **安全性**：`config.yaml` 文件包含敏感信息（如 API 密钥），已加入 `.gitignore`，请勿将其提交到版本控制系统
2. **配置持久化**：通过 Gradio UI 点击 "Apply Configuration" 后，修改会自动写入 `config.yaml`
3. **环境变量优先**：容器/K8s 部署时，通过环境变量注入密钥（如 `OPENAI_API_KEY`），环境变量值优先于 `config.yaml` 中的设置
4. **语言切换**：修改 `language` 配置后需要重启应用程序才能生效
5. **模型兼容性**：确保所选的模型与你的使用场景兼容
6. **类型保留**：YAML 格式保留正确的原始类型（整数、浮点数、布尔值、null、字符串），不再是全字符串
7. **热加载**：手动编辑 `config.yaml` 后，运行中的应用会在 `config_reload_interval` 秒内自动加载新配置，无需重启
8. **环境变量 Fallback**：
   - OpenAI 配置支持 `OPENAI_BASE_URL` 和 `OPENAI_API_KEY` 等环境变量覆盖
   - Cohere 支持 `CO_API_URL` 环境变量
   - 向量数据库支持对应环境变量（`QDRANT_HOST`、`MILVUS_HOST` 等）
9. **Ollama 配置完整性**：
   - 每个 LLM 类型（chat、extract、text2gql）都有对应的 `*_LANGUAGE_MODEL` 配置项
   - 每个服务类型都有独立的 host 和 port 配置，支持分布式部署

## 配置文件位置

### 系统配置（config.yaml 文件）

- **主配置文件**：`hugegraph-llm/config.yaml`
- **管理范围**：
  - `llm` section：语言、LLM 提供商配置、API 密钥等
  - `hugegraph` section：数据库连接、查询限制等
  - `admin` section：登录设置、令牌、热加载间隔等
  - `index` section：向量数据库连接参数

### 旧版 .env 兼容

- **旧版文件**：`hugegraph-llm/.env`
- **迁移行为**：首次启动时若 `config.yaml` 不存在而 `.env` 存在，系统会自动将 `.env` 内容迁移到 `config.yaml`，并保留原 `.env` 作为备份

### 提示词配置（YAML 文件）

- **配置文件**：`src/hugegraph_llm/resources/demo/config_prompt.yaml`
- **管理范围**：
  - PromptConfig：所有提示词模板、图谱模式等

### 配置类定义

- **位置**：`hugegraph-llm/src/hugegraph_llm/config/`
- **基类**：
  - BaseConfig：用于 YAML 文件管理的配置类（基于 OmegaConf + pydantic BaseModel）
  - BasePromptConfig：用于提示词 YAML 文件管理的配置类
  - ConfigManager：OmegaConf 单例管理器，负责 YAML 读写、环境变量覆盖、热加载
- **UI 配置管理**：`src/hugegraph_llm/demo/rag_demo/configs_block.py`
  - Gradio 界面的配置管理组件

### 部署配置文件

- **Docker 环境模板**：`docker/env.template`
  - 用于 Docker 容器部署的环境变量模板
- **Helm Chart 配置**：`docker/charts/hg-llm/values.yaml`
  - Kubernetes 部署配置，包含副本数、镜像、服务等设置

### 项目配置文件

- **Python 包配置**：`pyproject.toml`
  - 项目依赖、构建系统和包管理配置
- **JSON 示例文件**：`resources/` 目录下的各种 JSON 文件
  - 包含示例数据、查询样本等

## 相关文档

- [HugeGraph LLM README](README.md)
