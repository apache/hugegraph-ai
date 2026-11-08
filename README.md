# Apache HugeGraph AI

[![License](https://img.shields.io/badge/license-Apache%202-0E78BA.svg)](https://www.apache.org/licenses/LICENSE-2.0.html)
[![Ask DeepWiki](https://img.shields.io/badge/Ask-DeepWiki-blue)](https://deepwiki.com/apache/hugegraph-ai)

HugeGraph AI is the Python toolkit for building AI and data applications on [Apache HugeGraph](https://github.com/apache/hugegraph). It includes GraphRAG and knowledge-graph workflows, reusable extraction APIs, an MCP server, Python clients and graph machine-learning modules.

**Start here:** [Choose a module](#choose-a-module) · [Quick start](#quick-start) · [Documentation](#documentation) · [Development](#development)

## Choose a module

| Goal | Module |
|---|---|
| Build a GraphRAG or knowledge-graph application | [`hugegraph-llm`](hugegraph-llm/) |
| Embed schema design and reviewed graph extraction in another Python project | [`hugegraph-llm-sdk`](hugegraph-llm-sdk/) |
| Connect an MCP client to HugeGraph tools | [`hugegraph-mcp`](hugegraph-mcp/) |
| Access HugeGraph from Python | [`hugegraph-python-client`](hugegraph-python-client/) |
| Run graph-learning models and examples | [`hugegraph-ml`](hugegraph-ml/) |
| Call Vermeer from Python | [`vermeer-python-client`](vermeer-python-client/) |

`hugegraph-llm-sdk` owns reusable schema and extraction contracts. `hugegraph-llm` is the application layer and depends on the SDK and Python client. Changes to either shared package require validation of their application callers.

```text
Applications and MCP clients
           │
           ├─ hugegraph-llm-sdk ──► model providers
           ├─ hugegraph-llm ──────► GraphRAG, extraction and API/UI
           └─ hugegraph-mcp ──────► controlled graph tools
                         │
                         ▼
             hugegraph-python-client
                         │
                         ▼
                  HugeGraph Server
```

## Quick start

The main workspace uses Python 3.12 or later and [`uv`](https://docs.astral.sh/uv/). Read exact Python and dependency constraints from the root and module `pyproject.toml` files.

### Run the LLM application from source

Start a HugeGraph Server, then install the LLM dependency set:

```bash
git clone https://github.com/apache/hugegraph-ai.git
cd hugegraph-ai
uv sync --extra llm
source .venv/bin/activate
cd hugegraph-llm
python -m hugegraph_llm.demo.rag_demo.app
```

Open `http://127.0.0.1:8001`. The source launcher binds to loopback by default. Follow the [LLM module guide](hugegraph-llm/) for model, embedding, vector-index and HugeGraph configuration.

### Run the Docker environment

```bash
git clone https://github.com/apache/hugegraph-ai.git
cd hugegraph-ai/docker
cp env.template .env
# Set PROJECT_PATH and required model credentials in .env
docker compose -f docker-compose-network.yml up -d
```

The Compose environment includes HugeGraph and the RAG service. The RAG HTTP API is unauthenticated by default for local use; before exposing it, enable the built-in Bearer authentication with `ENABLE_LOGIN=true` and a strong `USER_TOKEN`, or place it behind an authenticated reverse proxy and trusted network boundary.

### Use a library instead of the application

- Install and integrate [`hugegraph-llm-sdk`](hugegraph-llm-sdk/) when another project needs schema design, validation or reviewed extraction without the demo application.
- Install `hugegraph-python` and import `pyhugegraph` when an application only needs the HugeGraph Python client.
- Run [`hugegraph-mcp`](hugegraph-mcp/) when an MCP host needs typed graph tools, read-only defaults and controlled write confirmation.

Each module README owns its package name, optional extras, API examples and compatibility boundary. Keeping those details beside the package avoids stale copies in this root README.

## Modules

### `hugegraph-llm-sdk`

Reusable synchronous and asynchronous APIs for schema design, validation and property-graph extraction. Provider adapters are optional so the base package can remain independent of application and account-specific dependencies. See the [SDK architecture](docs/sdk/architecture.md).

### `hugegraph-llm`

Application services and examples for GraphRAG, knowledge-graph construction, natural-language graph access, prompt workflows, model configuration and the RAG API/UI.

### `hugegraph-mcp`

Model Context Protocol server with typed schema, graph, Gremlin and extraction tools. It defaults to constrained behavior and requires explicit confirmation for protected writes.

### `hugegraph-python-client`

Python interface for schema, graph, traverser, variable, task and Gremlin operations. The distribution name is `hugegraph-python`; the import package is `pyhugegraph`.

### `hugegraph-ml` and `vermeer-python-client`

Graph-learning algorithms and the Vermeer client are lower-frequency standalone modules. Follow their own environment and compatibility instructions instead of assuming they share every workspace dependency.

## Documentation

- [Repository documentation index](docs/README.md): quality, testing, SDK architecture, release and documentation ownership.
- [LLM module](hugegraph-llm/): GraphRAG, extraction, configuration, API and deployment details.
- [SDK module](hugegraph-llm-sdk/): standalone installation and library integration.
- [MCP module](hugegraph-mcp/): server setup, client configuration, toolsets and safety behavior.
- [Official HugeGraph AI guide](https://hugegraph.apache.org/docs/quickstart/hugegraph-ai/): user-facing overview and deployment documentation.
- [`AGENTS.md`](AGENTS.md): repository boundaries, testing expectations and agent navigation.

Every durable document should be reachable from the repository index or a module-local README. Avoid duplicating a module procedure in the root README, quality docs and agent instructions.

## Development

Install workspace dependencies and run the checks for the modules you changed:

```bash
uv sync --all-extras
uv run --extra dev ruff format --check .
uv run --extra dev ruff check .
uv run --extra dev ty check hugegraph-llm/src/hugegraph_llm hugegraph-python-client/src/pyhugegraph
uv run --extra dev ty check hugegraph-llm-sdk/src/hugegraph_llm_sdk
```

Run tests from the affected module. Shared SDK or Python-client changes also require the relevant `hugegraph-llm` tests. See [CI policy](docs/quality/ci.md) and [`AGENTS.md`](AGENTS.md) for test selection; do not default to an expensive full-repository sweep when a precise affected-module set is available.

## Related projects

- [Apache HugeGraph](https://github.com/apache/hugegraph): Server, PD, distributed Store and Helm chart.
- [Apache HugeGraph Toolchain](https://github.com/apache/hugegraph-toolchain): Java client, Loader, Hubble, Tools and Spark connector.
- [Apache HugeGraph Computer](https://github.com/apache/hugegraph-computer): graph computation and Vermeer.
- [Apache HugeGraph Documentation](https://github.com/apache/hugegraph-doc): website and long-form user documentation.

## Community and license

- [Contribution guide](https://hugegraph.apache.org/docs/contribution-guidelines/)
- [Issue tracker](https://github.com/apache/hugegraph-ai/issues)
- [Developer mailing list](mailto:dev@hugegraph.apache.org)

HugeGraph AI is licensed under the [Apache License 2.0](LICENSE).
