# HugeGraph-LLM [![Ask DeepWiki](https://img.shields.io/badge/Ask-DeepWiki-blue)](https://deepwiki.com/apache/hugegraph-ai)

> **Bridge the gap between Graph Databases and Large Language Models**

## 🎯 Overview

HugeGraph-LLM is a comprehensive toolkit that combines the power of graph databases with large language models. It enables seamless integration between HugeGraph and LLMs for building intelligent applications.

### Key Features

- 🏗️ **Knowledge Graph Construction** - Build KGs automatically using LLMs + HugeGraph
- 🗣️ **Natural Language Querying** - Operate graph databases using natural language (Gremlin/Cypher)
- 🔍 **Graph-Enhanced RAG** - Leverage knowledge graphs to improve answer accuracy (GraphRAG & Graph Agent)

For detailed source code doc, visit our [DeepWiki](https://deepwiki.com/apache/hugegraph-ai) page. (Recommended)

### Reviewed Property-Graph Extraction

Enable optional review, bounded repair, and concurrent chunks through
`review_options` on `/graph/extract`. Accepted graphs are aggregated while every
chunk's status, issues, and call counts remain available. Requests without the
option keep the existing extraction path.
See the [runtime guide](docs/extraction-runtime.md) for a runnable example and
response semantics, and the [architecture explanation (中文)](docs/extraction-runtime-architecture.zh-CN.md).

### Use Graph Design and Extraction in Another Python Project

The independent [HugeGraph-LLM SDK](../hugegraph-llm-sdk/README.md) currently provides schema design,
validation, and reviewed extraction without Gradio, the application server, or a graph database connection.
Use synchronous or asynchronous calls, inject your existing model, and customize prompts, validators, or
individual pipeline steps. The application retains its existing UI, HTTP, and configuration contracts while
sharing the SDK implementation. The sibling `hugegraph-llm-sdk/` package can be installed separately from this
application; graph retrieval, persistence, and indexing remain application features. See the SDK guide for
editable source installation and offline examples.

## 📋 Prerequisites

> [!IMPORTANT]
>
> - **Python**: 3.12–3.14 (`>=3.12,<3.15`)
> - **HugeGraph Server**: 1.3+ (recommended: 1.5+)
> - **UV Package Manager**: 0.13.6+

Dependency ranges live in each package's `pyproject.toml`, so standalone installs
and workspace installs use the same requirements. The application uses Gradio 6,
Pydantic 2, NumPy 2 and current provider libraries. Unused PyArrow and igraph
requirements and root-level ML constraints have been removed; ML remains outside
the workspace.

A few upstream compatibility limits remain: LiteLLM requires OpenAI 2.x and its
Botocore dependency requires dateutil below 3. Jieba uses its built-in resource
fallback without requiring setuptools. `pycgraph` stays on 3.2.2 because 3.3.0 has no
CPython 3.14 Linux wheel or source distribution on PyPI. These limits do not prevent using
Python 3.12, 3.13 or 3.14.

Linux source installs build pycgraph from the pinned GitHub commit. Install Git,
a C++ compiler and Python development headers (Debian/Ubuntu:
`apt-get install git build-essential python3-dev`) and allow access to GitHub and
PyPI before running `uv sync`. The Docker builder includes this toolchain.

NLTK 3.10 refuses data directories writable by other accounts. Use a private,
user-owned `NLTK_DATA` cache. If a cache was ever writable by another account,
create a new private directory and download the corpora again with
`python -m nltk.downloader -d "$NLTK_DATA" stopwords punkt punkt_tab`; changing
permissions cannot restore file integrity. For a cache that was never shared and
whose contents are trusted, remove group and world write permissions with
`chmod -R go-w "$NLTK_DATA"`, then restart the application. A missing or refused
stopwords corpus is logged and falls back to an empty stopword list.

### Code Quality (uv + Ruff + ty)

Run all quality commands from the repository root.

- Ruff is used for linting and formatting:
  - `uv run --extra dev ruff format --check .`
  - `uv run --extra dev ruff check .`
- Type checking: `uv run --extra dev ty check hugegraph-llm/src/hugegraph_llm` from the repository root.
  CI runs it for affected modules in the existing test runner; existing diagnostics are advisory.
- Enable Git hooks via pre-commit:
  - `uv run --extra dev pre-commit install` (in the root dir)
  - `uv run --extra dev pre-commit run --all-files`
- Tool requirements: root `pyproject.toml` (`>=` for Ruff and ty). The [Ruff hooks](../.pre-commit-config.yaml) run through uv and inherit that range.

## 🚀 Quick Start

Choose your preferred deployment method:

### Option 1: Docker Compose (Recommended)

The fastest way to get started with both HugeGraph Server and RAG Service:

The image tags in these examples target the release prepared by this checkout.
They become available after publication. Before publication, build the image
from the repository root with `bash scripts/build_llm_image.sh` (Python 3.12+
is required; set `PYTHON_FOR_RELEASE=python3.12` if needed), or use
[Build from Source](#option-3-build-from-source).

The bundled Compose file defaults to the rolling Server image used by CI for
development/testing. For reproducible deployments, set `HUGEGRAPH_SERVER_IMAGE`
in `docker/.env` to a verified release tag or immutable digest. The override
does not change the CI image policy.

```bash
# 1. Set up environment
cp docker/env.template docker/.env
# Edit docker/.env and set PROJECT_PATH to your actual project path
# See "config.md" for all available configuration options
# If there is not a configuration file (named .env) under hugegraph-llm, run the following command
cd hugegraph-llm && touch .env && cd ..

# 2. Deploy services
cd docker
docker-compose -f docker-compose-network.yml up -d

# 3. Verify deployment
docker-compose -f docker-compose-network.yml ps

# 4. Access services
# HugeGraph Server: http://localhost:8080
# RAG Service: http://localhost:8001
```

The Compose configuration publishes the RAG service only on the host loopback interface by default.

### Option 2: Individual Docker Containers

For more control over individual components:

#### Available Images

- **`hugegraph/rag:1.8.0`** - Development image with source code access
- **`hugegraph/rag-bin`** - Production-optimized binary (compiled with Nuitka)

```bash
# 1. Create network
docker network create -d bridge hugegraph-net

# 2. Start HugeGraph Server
docker run -itd --name=server -p 8080:8080 --network hugegraph-net hugegraph/hugegraph:latest

# 3. Start RAG Service
docker pull hugegraph/rag:1.8.0
docker run -itd --name rag \
  -v /path/to/your/hugegraph-llm/.env:/home/work/hugegraph-llm/.env \
  -p 127.0.0.1:8001:8001 --network hugegraph-net hugegraph/rag:1.8.0

# 4. Monitor logs
docker logs -f rag
```

### Option 3: Build from Source

For development and customization:

```bash
# 1. Start HugeGraph Server
docker run -itd --name=server -p 8080:8080 hugegraph/hugegraph:latest

# 2. Install UV package manager (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Clone and setup project
git clone https://github.com/apache/hugegraph-ai.git
cd hugegraph-ai

# Configure environment if needed (see config.md); absent .env uses defaults

# 4. Install dependencies and activate environment
# NOTE: If download is slow, uncomment mirror lines in ../pyproject.toml or use: uv config --global index.url https://pypi.tuna.tsinghua.edu.cn/simple
# Or create local uv.toml with mirror settings to avoid git diff (see uv.toml example in root)
uv sync --extra llm  # Automatically creates .venv and installs dependencies
source .venv/bin/activate  # Activate once - all commands below assume this environment

# 5. Launch RAG demo
python -m hugegraph_llm.demo.rag_demo.app
# Access at: http://127.0.0.1:8001

# 6. (Optional) Custom host/port
python -m hugegraph_llm.demo.rag_demo.app --host 127.0.0.1 --port 18001
```

The Docker deployment publishes the RAG service on the host port by default, and the HTTP API is unauthenticated by
default. Before using this deployment outside a trusted local environment, either enable the built-in Bearer
authentication with `ENABLE_LOGIN=true` and a strong, non-default `USER_TOKEN`, or configure reverse proxy
authentication. Also restrict access with a firewall or trusted network. The source launcher can still be bound to
loopback explicitly with `--host 127.0.0.1`.

#### Additional Setup (Optional)

> [!NOTE]
> The following commands assume you're in the activated virtual environment from step 4 above

```bash
# To use vector database backends (e.g., Milvus, Qdrant), sync the optional dependencies:
uv sync --extra vectordb

# Download NLTK stopwords for better text processing
python ./src/hugegraph_llm/operators/common_op/nltk_helper.py

# Update configuration files
python -m hugegraph_llm.config.generate --update
```

> [!TIP]
>
> - `uv sync` automatically creates virtual environment (.venv) and installs all dependencies
> - Activate once with `source .venv/bin/activate` - all subsequent commands assume this environment
> - Check our [Quick Start Guide](https://github.com/apache/hugegraph-ai/blob/main/hugegraph-llm/quick_start.md) for detailed usage examples

## 💡 Usage Examples

### Knowledge Graph Construction

#### Interactive Web Interface

Use the Gradio interface for visual knowledge graph building:

**Input Options:**

- **Text**: Direct text input for RAG index creation
- **Files**: Upload TXT or DOCX files (multiple selection supported)

**Schema Configuration:**

- **Custom Schema**: JSON format following our [template](https://github.com/apache/hugegraph-ai/blob/aff3bbe25fa91c3414947a196131be812c20ef11/hugegraph-llm/src/hugegraph_llm/config/config_data.py#L125)
- **HugeGraph Schema**: Use existing graph instance schema (e.g., "hugegraph")

![Knowledge Graph Builder](https://raw.githubusercontent.com/hugegraph/hugegraph-ai/fb6a3d91c26fc82cc4e0a98667e9d49418659bcf/docs/images/gradio/graph-extraction.png)

After loading the extracted graph, open **Graph Tools** to run a Gremlin query:

![Graph Tools query](https://raw.githubusercontent.com/hugegraph/hugegraph-ai/fb6a3d91c26fc82cc4e0a98667e9d49418659bcf/docs/images/gradio/graph-query.png)

## 🔧 Configuration

Configuration paths for source checkouts (see [external configuration](config.md#外部挂载与配置所有权)):

- **Environment**: optional `hugegraph-llm/.env`; startup reads it without modifying it
- **Prompts**: optional `hugegraph-llm/src/hugegraph_llm/resources/demo/config_prompt.yaml`; absent files use built-in defaults

Provider settings can also be edited in the web interface. This example uses a
local model endpoint:

![LLM provider configuration](https://raw.githubusercontent.com/hugegraph/hugegraph-ai/fb6a3d91c26fc82cc4e0a98667e9d49418659bcf/docs/images/gradio/configuration.png)

### Language Support

The system supports both English and Chinese prompts. To switch languages:

1. **Edit `.env` file**: Change `LANGUAGE=en` to `LANGUAGE=CN` (or vice versa)
2. **Restart the application**: The system will automatically regenerate prompts in the selected language

**Supported Values:**

- `LANGUAGE=EN` - English prompts (default)
- `LANGUAGE=CN` - Chinese prompts (中文提示词)

> [!NOTE]
> Save model connections in the web interface or API; test connectivity separately. Saved complete connections in `settings.yaml` override deployment defaults across restarts/upgrades. Blank keys retain the saved key; use the explicit clear action to remove it. Unconfigured extraction/Text2GQL follow Chat. Persist the writable resource directory (or `HUGEGRAPH_LLM_SETTINGS_PATH`); readonly `.env`/Secret mounts remain supported as bootstrap defaults. See [configuration rules](config.md#网页api-配置与部署默认值).

### Legacy Thin API writes

The compatibility endpoints `POST /graph-import` and
`POST /vid-embeddings/refresh` are disabled by default. They are intended only
for authenticated internal callers. To enable them, set `ENABLE_LOGIN=true`,
replace the default `USER_TOKEN=4321` with a strong random secret, and set
`HUGEGRAPH_LLM_ENABLE_THIN_WRITES=true`. Send the configured `USER_TOKEN` as a
Bearer token. Prefer the HugeGraph MCP guarded write tools for user-facing
workflows.

**LLM Provider Support**: This project uses [LiteLLM](https://docs.litellm.ai/docs/providers) for multi-provider LLM support.

### Programmatic Examples (new workflow engine)

If you previously used high-level classes like `RAGPipeline` or `KgBuilder`, the project now exposes stable flows through the `Scheduler` API. Use `SchedulerSingleton.get_instance().schedule_flow(...)` to invoke workflows programmatically. Below are concise, working examples that match the new architecture.

1. RAG (graph-only) query example

```python
from hugegraph_llm.flows.scheduler import SchedulerSingleton

scheduler = SchedulerSingleton.get_instance()
res = scheduler.schedule_flow(
    "rag_graph_only",
    query="Tell me about Al Pacino.",
    graph_only_answer=True,
    vector_only_answer=False,
    raw_answer=False,
    gremlin_tmpl_num=-1,
    gremlin_prompt=None,
)

print(res.get("graph_only_answer"))
```

2. RAG (vector-only) query example

```python
from hugegraph_llm.flows.scheduler import SchedulerSingleton

scheduler = SchedulerSingleton.get_instance()
res = scheduler.schedule_flow(
    "rag_vector_only", query="Summarize the career of Ada Lovelace.", vector_only_answer=True, vector_search=True
)

print(res.get("vector_only_answer"))
```

3. Text -> Gremlin (text2gremlin) example

```python
from hugegraph_llm.flows.scheduler import SchedulerSingleton

scheduler = SchedulerSingleton.get_instance()
response = scheduler.schedule_flow(
    "text2gremlin",
    "find people who worked with Alan Turing",
    2,  # example_num
    "hugegraph",  # schema_input (graph name or schema)
    None,  # gremlin_prompt_input (optional)
    ["template_gremlin", "raw_gremlin"],
)

print(response.get("template_gremlin"))
```

4. Build example index (used by text2gremlin examples)

```python
from hugegraph_llm.flows.scheduler import SchedulerSingleton

examples = [{"id": "natural language query", "gremlin": "g.V().hasLabel('person').valueMap()"}]
res = SchedulerSingleton.get_instance().schedule_flow("build_examples_index", examples)
print(res)
```

### Migration guide: RAGPipeline / KgBuilder → Scheduler flows

Why the change: the internal execution engine was refactored to a pipeline-based scheduler (GPipeline + GPipelineManager). The scheduler provides a stable entrypoint while keeping flow implementations modular.

If you need help migrating a specific snippet, open a PR or issue and include the old code — we can provide a targeted conversion.

## 🤖 Developer Guidelines

> [!IMPORTANT] > **For developers contributing to hugegraph-llm with AI coding assistance:**
>
> - **Start Here**: First read `../rules/README.md` for the complete AI-assisted development workflow
> - **Module Context**: Rename `AGENTS.md` in this directory as context for your LLM (e.g., `CLAUDE.md`, `copilot-instructions.md`)
> - **Code Analysis**: Follow comprehensive analysis methodology in `../rules/prompts/project-deep.md`
> - **Documentation**: Maintain structured documentation standards from `../rules/prompts/project-general.md`
> - **Quality Standards**: Ensure type annotations, proper testing, and consistent patterns
> - **Business Logic**: Focus on graph-LLM integration logic and RAG pipeline optimization
>
> These guidelines ensure consistent code quality and maintainable graph-AI integrations.

## 📚 Additional Resources

- **Graph Visualization**: Use [HugeGraph Hubble](https://hub.docker.com/r/hugegraph/hubble) for data analysis and schema management
- **API Documentation**: Explore our REST API endpoints for integration
- **Community**: Join our discussions and contribute to the project

---

**License**: Apache License 2.0 | **Community**: [Apache HugeGraph](https://hugegraph.apache.org/)
