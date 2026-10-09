# HugeGraph LLM 配置选项 (详解)

本文档详细说明了 HugeGraph LLM 项目中所有的配置选项。配置分为以下几类：

1. **基础配置**：通过 `.env` 文件管理
2. **Prompt 配置**：通过 `config_prompt.yaml` 文件管理
3. **Docker 配置**：通过 Docker 和 Helm 配置文件管理
4. **项目配置**：通过 `pyproject.toml` 和 `JSON` 文件管理

## 目录

- [.env 配置文件](#env-配置文件)
  - [基础配置](#基础配置)
  - [OpenAI 配置](#openai-配置)
  - [Ollama 配置](#ollama-配置)
  - [LiteLLM 配置](#litellm-配置)
  - [重排序配置](#重排序配置)
  - [HugeGraph 数据库配置](#hugegraph-数据库配置)
  - [向量数据库配置](#向量数据库配置)
  - [管理员配置](#管理员配置)
- [配置使用示例](#配置使用示例)
- [配置文件位置](#配置文件位置)

## .env 配置文件

`.env` 文件位于 `hugegraph-llm/` 目录下，包含了系统运行所需的所有配置项。

### 基础配置

| 配置项                    | 类型                                                     | 默认值    | 说明                                    |
|------------------------|--------------------------------------------------------|--------|---------------------------------------|
| `LANGUAGE`             | Literal["EN", "CN"]                                    | EN     | prompt语言，支持 EN（英文）和 CN（中文）            |
| `CHAT_LLM_TYPE`        | Literal["openai", "litellm", "ollama/local"]           | openai | 聊天 LLM 类型：openai/litellm/ollama/local |
| `EXTRACT_LLM_TYPE`     | Literal["openai", "litellm", "ollama/local"]           | openai | 信息提取 LLM 类型                           |
| `TEXT2GQL_LLM_TYPE`    | Literal["openai", "litellm", "ollama/local"]           | openai | 文本转 GQL LLM 类型                        |
| `EMBEDDING_TYPE`       | Optional[Literal["openai", "litellm", "ollama/local"]] | openai | 嵌入模型类型                                |
| `RERANKER_TYPE`        | Optional[Literal["cohere", "siliconflow"]]             | None   | 重排序模型类型：cohere/siliconflow            |
| `KEYWORD_EXTRACT_TYPE` | Literal["llm", "textrank", "hybrid"]                   | llm    | 关键词提取模型类型：llm/textrank/hybrid         |
| `WINDOW_SIZE`          | Optional[Integer] | 3 | TextRank 滑窗大小 (范围: 1-10),较大的窗口可以捕获更长距离的词语关系,但会增加计算复杂度 |
| `HYBRID_LLM_WEIGHTS`   | Optional[Float] | 0.5 | 混合模式中 LLM 结果的权重 (范围: 0.0-1.0),TextRank 权重 = 1 - 该值。推荐 0.5 以平衡两种方法 |

### OpenAI 配置

| 配置项                              | 类型               | 默认值                       | 说明                        |
|----------------------------------|------------------|---------------------------|---------------------------|
| `OPENAI_CHAT_API_BASE`           | Optional[String] | https://api.openai.com/v1 | OpenAI 聊天 API 基础 URL      |
| `OPENAI_CHAT_API_KEY`            | Optional[String] | -                         | OpenAI 聊天 API 密钥          |
| `OPENAI_CHAT_LANGUAGE_MODEL`     | Optional[String] | gpt-4.1-mini              | 聊天模型名称                    |
| `OPENAI_CHAT_TOKENS`             | Integer          | 8192                      | 聊天最大令牌数                   |
| `OPENAI_EXTRACT_API_BASE`        | Optional[String] | https://api.openai.com/v1 | OpenAI 提取 API 基础 URL      |
| `OPENAI_EXTRACT_API_KEY`         | Optional[String] | -                         | OpenAI 提取 API 密钥          |
| `OPENAI_EXTRACT_LANGUAGE_MODEL`  | Optional[String] | gpt-4.1-mini              | 提取模型名称                    |
| `OPENAI_EXTRACT_TOKENS`          | Integer          | 256                       | 提取最大令牌数                   |
| `OPENAI_TEXT2GQL_API_BASE`       | Optional[String] | https://api.openai.com/v1 | OpenAI 文本转 GQL API 基础 URL |
| `OPENAI_TEXT2GQL_API_KEY`        | Optional[String] | -                         | OpenAI 文本转 GQL API 密钥     |
| `OPENAI_TEXT2GQL_LANGUAGE_MODEL` | Optional[String] | gpt-4.1-mini              | 文本转 GQL 模型名称              |
| `OPENAI_TEXT2GQL_TOKENS`         | Integer          | 4096                      | 文本转 GQL 最大令牌数             |
| `OPENAI_EMBEDDING_API_BASE`      | Optional[String] | https://api.openai.com/v1 | OpenAI 嵌入 API 基础 URL      |
| `OPENAI_EMBEDDING_API_KEY`       | Optional[String] | -                         | OpenAI 嵌入 API 密钥          |
| `OPENAI_EMBEDDING_MODEL`         | Optional[String] | text-embedding-3-small    | 嵌入模型名称                    |

#### OpenAI 环境变量

| 环境变量                        | 对应配置项                     | 说明                            |
|-----------------------------|---------------------------|-------------------------------|
| `OPENAI_BASE_URL`           | 所有 OpenAI API_BASE        | 通用 OpenAI API 基础 URL          |
| `OPENAI_API_KEY`            | 所有 OpenAI API_KEY         | 通用 OpenAI API 密钥              |
| `OPENAI_EMBEDDING_BASE_URL` | OPENAI_EMBEDDING_API_BASE | OpenAI 嵌入 API 基础 URL          |
| `OPENAI_EMBEDDING_API_KEY`  | OPENAI_EMBEDDING_API_KEY  | OpenAI 嵌入 API 密钥              |
| `CO_API_URL`                | COHERE_BASE_URL           | Cohere API URL（环境变量 fallback） |

### Ollama 配置

| 配置项                              | 类型                | 默认值       | 说明                  |
|----------------------------------|-------------------|-----------|---------------------|
| `OLLAMA_CHAT_HOST`               | Optional[String]  | 127.0.0.1 | Ollama 聊天服务主机       |
| `OLLAMA_CHAT_PORT`               | Optional[Integer] | 11434     | Ollama 聊天服务端口       |
| `OLLAMA_CHAT_LANGUAGE_MODEL`     | Optional[String]  | -         | Ollama 聊天模型名称       |
| `OLLAMA_EXTRACT_HOST`            | Optional[String]  | 127.0.0.1 | Ollama 提取服务主机       |
| `OLLAMA_EXTRACT_PORT`            | Optional[Integer] | 11434     | Ollama 提取服务端口       |
| `OLLAMA_EXTRACT_LANGUAGE_MODEL`  | Optional[String]  | -         | Ollama 提取模型名称       |
| `OLLAMA_TEXT2GQL_HOST`           | Optional[String]  | 127.0.0.1 | Ollama 文本转 GQL 服务主机 |
| `OLLAMA_TEXT2GQL_PORT`           | Optional[Integer] | 11434     | Ollama 文本转 GQL 服务端口 |
| `OLLAMA_TEXT2GQL_LANGUAGE_MODEL` | Optional[String]  | -         | Ollama 文本转 GQL 模型名称 |
| `OLLAMA_EMBEDDING_HOST`          | Optional[String]  | 127.0.0.1 | Ollama 嵌入服务主机       |
| `OLLAMA_EMBEDDING_PORT`          | Optional[Integer] | 11434     | Ollama 嵌入服务端口       |
| `OLLAMA_EMBEDDING_MODEL`         | Optional[String]  | -         | Ollama 嵌入模型名称       |

### LiteLLM 配置

| 配置项                               | 类型               | 默认值                           | 说明                         |
|-----------------------------------|------------------|-------------------------------|----------------------------|
| `LITELLM_CHAT_API_KEY`            | Optional[String] | -                             | LiteLLM 聊天 API 密钥          |
| `LITELLM_CHAT_API_BASE`           | Optional[String] | -                             | LiteLLM 聊天 API 基础 URL      |
| `LITELLM_CHAT_LANGUAGE_MODEL`     | Optional[String] | openai/gpt-4.1-mini           | LiteLLM 聊天模型名称             |
| `LITELLM_CHAT_TOKENS`             | Integer          | 8192                          | 聊天最大令牌数                    |
| `LITELLM_EXTRACT_API_KEY`         | Optional[String] | -                             | LiteLLM 提取 API 密钥          |
| `LITELLM_EXTRACT_API_BASE`        | Optional[String] | -                             | LiteLLM 提取 API 基础 URL      |
| `LITELLM_EXTRACT_LANGUAGE_MODEL`  | Optional[String] | openai/gpt-4.1-mini           | LiteLLM 提取模型名称             |
| `LITELLM_EXTRACT_TOKENS`          | Integer          | 256                           | 提取最大令牌数                    |
| `LITELLM_TEXT2GQL_API_KEY`        | Optional[String] | -                             | LiteLLM 文本转 GQL API 密钥     |
| `LITELLM_TEXT2GQL_API_BASE`       | Optional[String] | -                             | LiteLLM 文本转 GQL API 基础 URL |
| `LITELLM_TEXT2GQL_LANGUAGE_MODEL` | Optional[String] | openai/gpt-4.1-mini           | LiteLLM 文本转 GQL 模型名称       |
| `LITELLM_TEXT2GQL_TOKENS`         | Integer          | 4096                          | 文本转 GQL 最大令牌数              |
| `LITELLM_EMBEDDING_API_KEY`       | Optional[String] | -                             | LiteLLM 嵌入 API 密钥          |
| `LITELLM_EMBEDDING_API_BASE`      | Optional[String] | -                             | LiteLLM 嵌入 API 基础 URL      |
| `LITELLM_EMBEDDING_MODEL`         | Optional[String] | openai/text-embedding-3-small | LiteLLM 嵌入模型名称             |

### 重排序配置

| 配置项                | 类型               | 默认值                              | 说明                 |
|--------------------|------------------|----------------------------------|--------------------|
| `COHERE_BASE_URL`  | Optional[String] | https://api.cohere.com/v1/rerank | Cohere 重排序 API URL |
| `RERANKER_API_KEY` | Optional[String] | -                                | 重排序 API 密钥         |
| `RERANKER_MODEL`   | Optional[String] | -                                | 重排序模型名称            |

### HugeGraph 数据库配置

| 配置项                    | 类型                | 默认值            | 说明                 |
|------------------------|-------------------|----------------|--------------------|
| `GRAPH_URL`            | Optional[String]  | 127.0.0.1:8080 | HugeGraph 服务器地址    |
| `GRAPH_NAME`           | Optional[String]  | hugegraph      | 图数据库名称             |
| `GRAPH_USER`           | Optional[String]  | admin          | 数据库用户名             |
| `GRAPH_PWD`            | Optional[String]  | xxx            | 数据库密码              |
| `GRAPH_SPACE`          | Optional[String]  | -              | 图空间名称（可选）          |
| `LIMIT_PROPERTY`       | Optional[String]  | "False"        | 是否限制属性（注意：这是字符串类型） |
| `MAX_GRAPH_PATH`       | Optional[Integer] | 10             | 最大图路径长度            |
| `MAX_GRAPH_ITEMS`      | Optional[Integer] | 30             | 最大图项目数             |
| `EDGE_LIMIT_PRE_LABEL` | Optional[Integer] | 8              | 每个标签的边数限制          |
| `VECTOR_DIS_THRESHOLD` | Optional[Float]   | 0.9            | 向量距离阈值             |
| `TOPK_PER_KEYWORD`     | Optional[Integer] | 1              | 每个关键词返回的 TopK 数量   |
| `TOPK_RETURN_RESULTS`  | Optional[Integer] | 20             | 返回结果数量             |

### 向量数据库配置

| 配置项              | 类型               | 默认值  | 说明                     |
|------------------|------------------|-------|------------------------|
| `QDRANT_HOST`    | Optional[String] | None  | Qdrant 服务器主机地址         |
| `QDRANT_PORT`    | Integer          | 6333  | Qdrant 服务器端口           |
| `QDRANT_API_KEY` | Optional[String] | None  | Qdrant API 密钥（如果设置了的话） |
| `MILVUS_HOST`    | Optional[String] | None  | Milvus 服务器主机地址         |
| `MILVUS_PORT`    | Integer          | 19530 | Milvus 服务器端口           |
| `MILVUS_USER`    | String           | ""    | Milvus 用户名              |
| `MILVUS_PASSWORD`| String           | ""    | Milvus 密码               |

### 管理员配置

| 配置项            | 类型               | 默认值     | 说明                 |
|----------------|------------------|---------|--------------------|
| `ENABLE_LOGIN` | Optional[String] | "False" | 是否启用登录（注意：这是字符串类型） |
| `USER_TOKEN`   | Optional[String] | 4321    | 用户令牌               |
| `ADMIN_TOKEN`  | Optional[String] | xxxx    | 管理员令牌              |

## 配置使用示例

### 1. 基础配置示例

```properties
# 基础设置
LANGUAGE=EN
CHAT_LLM_TYPE=openai
EXTRACT_LLM_TYPE=openai
TEXT2GQL_LLM_TYPE=openai
EMBEDDING_TYPE=openai

# OpenAI 配置
OPENAI_CHAT_API_KEY=your-openai-api-key
OPENAI_CHAT_LANGUAGE_MODEL=gpt-4.1-mini
OPENAI_EMBEDDING_API_KEY=your-openai-embedding-key
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# HugeGraph 配置
GRAPH_URL=127.0.0.1:8080
GRAPH_NAME=hugegraph
GRAPH_USER=admin
GRAPH_PWD=your-password
```

### 2. 使用 Ollama 的配置示例

```properties
# 使用 Ollama
CHAT_LLM_TYPE=ollama/local
EXTRACT_LLM_TYPE=ollama/local
TEXT2GQL_LLM_TYPE=ollama/local
EMBEDDING_TYPE=ollama/local

# Ollama 模型配置
OLLAMA_CHAT_LANGUAGE_MODEL=llama2
OLLAMA_EXTRACT_LANGUAGE_MODEL=llama2
OLLAMA_TEXT2GQL_LANGUAGE_MODEL=llama2
OLLAMA_EMBEDDING_MODEL=nomic-embed-text

# Ollama 服务配置（如果需要自定义）
OLLAMA_CHAT_HOST=127.0.0.1
OLLAMA_CHAT_PORT=11434
OLLAMA_EXTRACT_HOST=127.0.0.1
OLLAMA_EXTRACT_PORT=11434
OLLAMA_TEXT2GQL_HOST=127.0.0.1
OLLAMA_TEXT2GQL_PORT=11434
OLLAMA_EMBEDDING_HOST=127.0.0.1
OLLAMA_EMBEDDING_PORT=11434
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

## 注意事项

1. **安全性**：`.env` 文件包含敏感信息（如 API 密钥），请勿将其提交到版本控制系统
2. **配置同步**：修改配置后，系统会自动同步到 `.env` 文件
3. **语言切换**：修改 `LANGUAGE` 配置后需要重启应用程序才能生效
4. **模型兼容性**：确保所选的模型与你的使用场景兼容
5. **资源限制**：根据你的硬件资源调整 `MAX_GRAPH_ITEMS`、`EDGE_LIMIT_PRE_LABEL` 等参数
6. **类型注意**：
   - `LIMIT_PROPERTY` 和 `ENABLE_LOGIN` 是字符串类型（\"False\"/\"True\"），不是布尔类型
   - `LANGUAGE`、`CHAT_LLM_TYPE` 等字段使用 Literal 类型限制可选值
   - 大部分字段都是 Optional 类型，支持 None 值，表示未设置
7. **环境变量 Fallback**：
   - OpenAI 配置支持 `OPENAI_BASE_URL` 和 `OPENAI_API_KEY` 环境变量作为 fallback
   - OpenAI Embedding 支持独立的环境变量 `OPENAI_EMBEDDING_BASE_URL` 和 `OPENAI_EMBEDDING_API_KEY`
   - Cohere 支持 `CO_API_URL` 环境变量
8. **Ollama 配置完整性**：
   - 每个 LLM 类型（chat、extract、text2gql）都有对应的 `*_LANGUAGE_MODEL` 配置项
   - 每个服务类型都有独立的 host 和 port 配置，支持分布式部署

## 配置文件位置

### 系统配置（.env 文件）

- **主配置文件**：`hugegraph-llm/.env`
- **管理范围**：
  - LLMConfig：语言、LLM 提供商配置、API 密钥等
  - HugeGraphConfig：数据库连接、查询限制等
  - AdminConfig：登录设置、令牌等

### 提示词配置（YAML 文件）

- **配置文件**：`src/hugegraph_llm/resources/demo/config_prompt.yaml`
- **管理范围**：
  - PromptConfig：所有提示词模板、图谱模式等
  - **注意**：这些配置不存储在 .env 文件中

### 配置类定义

- **位置**：`hugegraph-llm/src/hugegraph_llm/config/`
- **基类**：
  - BaseConfig：用于 .env 文件管理的配置类
  - BasePromptConfig：用于 YAML 文件管理的提示词配置类
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
