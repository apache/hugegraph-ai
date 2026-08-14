# hugegraph-ai

[![License](https://img.shields.io/badge/license-Apache%202-0E78BA.svg)](https://www.apache.org/licenses/LICENSE-2.0.html)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/apache/hugegraph-ai)

`hugegraph-ai` integrates [HugeGraph](https://github.com/apache/hugegraph) with artificial intelligence capabilities, providing comprehensive support for developers to build AI-powered graph applications.

## ✨ Key Features

- **[LLM/GraphRAG](./hugegraph-llm/README.md#graphrag)**: Build intelligent question-answering systems with graph-enhanced retrieval
- **[Knowledge Graph Construction](./hugegraph-llm/README.md#knowledge-graph-construction)**: Automated graph building from text using LLMs
- **[Graph ML](./hugegraph-ml/README.md)**: Integration with 20+ graph learning algorithms (GCN, GAT, GraphSAGE, etc.)
- **[HG-Python Client](./hugegraph-python-client/README.md)**: Easy-to-use Python interface for HugeGraph operations
- **[Vermeer Python Client](./vermeer-python-client/README.md)**: SDK/Interface for Graph Computing with [Vermeer](https://github.com/apache/hugegraph-computer/tree/master/vermeer#readme)

## 🚀 Quick Start

> [!NOTE]
> For a complete deployment guide and detailed examples, please refer to [hugegraph-llm/README.md](./hugegraph-llm/README.md)

### Prerequisites

- Python 3.10+ (required for hugegraph-llm)
- [uv](https://docs.astral.sh/uv/) 0.7+ (required for workspace management)
- HugeGraph Server 1.3+ for the LLM/client modules (1.5+ recommended); `hugegraph-mcp` requires 1.7.0+
- Docker (optional, for containerized deployment)

### Option 1: Docker Deployment (Recommended)

```bash
# Clone the repository
git clone https://github.com/apache/hugegraph-ai.git
cd hugegraph-ai

# Set up environment and start services
cp docker/env.template docker/.env
# Edit docker/.env to set your PROJECT_PATH
cd docker
# same as `docker-compose` (Legacy)
docker compose -f docker-compose-network.yml up -d

# Access services:
# - HugeGraph Server: http://localhost:8080
# - RAG Service: http://localhost:8001
```

The RAG service is published on the host port by default, and the HTTP API is unauthenticated by default. Before
using this deployment outside a trusted local environment, either enable the built-in Bearer authentication with
`ENABLE_LOGIN=true` and a strong, non-default `USER_TOKEN`, or configure reverse proxy authentication. Also restrict
access with a firewall or trusted network.

### Option 2: Source Installation

```bash
# 1. Start HugeGraph Server
docker run -itd --name=server -p 8080:8080 hugegraph/hugegraph

# 2. Clone and set up the project
git clone https://github.com/apache/hugegraph-ai.git
cd hugegraph-ai

# 3. Install dependencies with workspace management
# uv sync automatically creates venv (.venv) and installs base dependencies
# NOTE: If download is slow, uncomment mirror lines in pyproject.toml or use: uv config --global index.url https://pypi.tuna.tsinghua.edu.cn/simple
# Or create local uv.toml with mirror settings to avoid git diff (see uv.toml example in root)
uv sync --extra llm  # Install LLM-specific dependencies
# For HugeGraph MCP source development, install its standalone package directly.
# Or install all optional dependencies: uv sync --all-extras

# 4. Activate virtual environment (recommended for easier commands)
source .venv/bin/activate

# 5. Start the demo (no uv run prefix needed when venv activated)
cd hugegraph-llm
python -m hugegraph_llm.demo.rag_demo.app
# Visit http://127.0.0.1:8001
```

The source launcher binds to `127.0.0.1` by default and warns when a non-loopback `--host` is selected.

### Basic Usage Examples

> [!NOTE]
> Examples assume you've activated the virtual environment with `source .venv/bin/activate`

#### Graph Machine Learning

```bash
# Install ML dependencies (ml module is not in workspace)
uv sync --extra ml
source .venv/bin/activate

# Run ML algorithms
cd hugegraph-ml
python examples/your_ml_example.py
```

## 📦 Modules

### [hugegraph-llm](./hugegraph-llm) [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/apache/hugegraph-ai)

Large language model integration for graph applications:

- **GraphRAG**: Retrieval-augmented generation with graph data
- **Knowledge Graph Construction**: Build KGs from text automatically
- **Natural Language Interface**: Query graphs using natural language
- **AI Agents**: Intelligent graph analysis and reasoning

### [hugegraph-mcp](./hugegraph-mcp)

Model Context Protocol server for safe, controlled HugeGraph access:

- **Stable Tool Contract**: Typed graph, schema, Gremlin, and extraction tools for MCP clients
- **Safe Writes**: Read-only defaults plus dry-run, persistent single-use confirmation, and target revalidation
- **Compatibility**: Default `v2_core` toolset with an opt-in `v1` compatibility mode

### [hugegraph-ml](./hugegraph-ml)

Graph machine learning with 20+ implemented algorithms:

- **Node Classification**: GCN, GAT, GraphSAGE, APPNP, etc.
- **Graph Classification**: DiffPool, P-GNN, etc.
- **Graph Embedding**: DeepWalk, Node2Vec, GRACE, etc.
- **Link Prediction**: SEAL, GATNE, etc.

> [!NOTE]
> hugegraph-ml is not part of the workspace but linked via path dependency

### [hugegraph-python-client](./hugegraph-python-client)

Python client for HugeGraph operations:

- **Schema Management**: Define vertex/edge labels and properties
- **CRUD Operations**: Create, read, update, delete graph data
- **Gremlin Queries**: Execute graph traversal queries
- **REST API**: Complete HugeGraph REST API coverage

## 📚 Learn More

- [Project Homepage](https://hugegraph.apache.org/docs/quickstart/hugegraph-ai/)
- [LLM Quick Start Guide](./hugegraph-llm/quick_start.md)
- [DeepWiki AI Documentation](https://deepwiki.com/apache/hugegraph-ai)

## 🔗 Related HugeGraph Projects

And here are links of other repositories:

1. [hugegraph](https://github.com/apache/hugegraph) (graph's core component - Graph server + PD + Store)
2. [hugegraph-toolchain](https://github.com/apache/hugegraph-toolchain) (graph tools **[loader](https://github.com/apache/hugegraph-toolchain/tree/master/hugegraph-loader)/[dashboard](https://github.com/apache/hugegraph-toolchain/tree/master/hugegraph-hubble)/[tool](https://github.com/apache/hugegraph-toolchain/tree/master/hugegraph-tools)/[client](https://github.com/apache/hugegraph-toolchain/tree/master/hugegraph-client)**)
3. [hugegraph-computer](https://github.com/apache/hugegraph-computer) (integrated **graph computing** system)
4. [hugegraph-website](https://github.com/apache/hugegraph-doc) (**doc & website** code)

## 🤝 Contributing

We welcome contributions! Please see our [contribution guidelines](https://hugegraph.apache.org/docs/contribution-guidelines/) for details.

### 🤖 AI Coding Guidelines for Developers

> [!IMPORTANT] > **For project contributors using AI coding tools**, please follow these guidelines:
>
> - **Start Here**: First read `rules/README.md` for the complete AI-assisted development workflow
> - **Module Context**: When `AGENTS.md` exists in any module, rename it as context for your LLM (e.g., `CLAUDE.md`, `copilot-instructions.md`)
> - **Documentation Standards**: Follow the structured documentation approach in `rules/prompts/project-general.md`
> - **Deep Analysis**: For complex features, refer to `rules/prompts/project-deep.md` for comprehensive code analysis methodology
> - **Code Quality**: Maintain consistency with existing patterns and ensure proper type annotations
> - **Testing**: Follow TDD principles and ensure comprehensive test coverage for new features
>
> These guidelines ensure consistent code quality and maintainable development workflow with AI assistance.

**Development Setup:**

```bash
# 1. Clone and navigate to project
git clone https://github.com/apache/hugegraph-ai.git
cd hugegraph-ai

# 2. Install all development dependencies
# uv sync creates venv automatically and installs base dependencies
uv sync --all-extras  # Install all optional dependency groups
source .venv/bin/activate  # Activate for easier command usage

# 3. Run tests for workspace members
cd hugegraph-llm && pytest
cd ../hugegraph-python-client && pytest

# 4. Run tests for path dependencies
cd ../hugegraph-ml && pytest  # If tests exist

# 5. Format and lint code
./style/code_format_and_analysis.sh

# 6. Add new dependencies to workspace
uv add numpy  # Add to base dependencies
uv add --group dev pytest-mock  # Add to dev group
```

### Code Quality (ruff + pre-commit)

- Ruff is used for linting and formatting:
  - \`ruff format .\`
  - \`ruff check .\`
- Enable Git hooks via pre-commit:
  - \`pre-commit install\`
  - \`pre-commit run --all-files\`
- Config: [.pre-commit-config.yaml](.pre-commit-config.yaml). CI enforces these checks.
  **Key Points:**
- Config: [.pre-commit-config.yaml](.pre-commit-config.yaml). CI enforces these checks.

**Key Points:**
- Use [GitHub Desktop](https://desktop.github.com/) for easier PR management
- Check existing issues before reporting bugs

[![contributors graph](https://contrib.rocks/image?repo=apache/hugegraph-ai)](https://github.com/apache/hugegraph-ai/graphs/contributors)

## 📄 License

hugegraph-ai is licensed under [Apache 2.0 License](./LICENSE).

## 📞 Contact Us

- **GitHub Issues**: [Report bugs or request features](https://github.com/apache/hugegraph-ai/issues) (fastest response)
- **Email**: [dev@hugegraph.apache.org](mailto:dev@hugegraph.apache.org) ([subscription required](https://hugegraph.apache.org/docs/contribution-guidelines/subscribe/))
- **Slack**: [Join the ASF HugeGraph channel](https://the-asf.slack.com/archives/C059UU2FJ23)
- **WeChat**: Follow "Apache HugeGraph" official account

<img src="https://raw.githubusercontent.com/apache/hugegraph-doc/master/assets/images/wechat.png" alt="Apache HugeGraph WeChat QR Code" width="200"/>
