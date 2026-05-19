# Basic Introduction

This file provides guidance to AI coding tools and developers when working with code in this repository.

## Project Overview

HugeGraph-LLM is a comprehensive toolkit that bridges graph databases and large language models,
part of the Apache HugeGraph AI ecosystem. It enables seamless integration between HugeGraph and LLMs for building
intelligent applications with three main capabilities: Knowledge Graph Construction, Graph-Enhanced RAG,
and Text2Gremlin query generation.

## Tech Stack

- **Language**: Python 3.10+ (uv package manager required)
- **Framework**: FastAPI + Gradio for web interfaces
- **Graph Database**: HugeGraph Server 1.5+
- **LLM Integration**: LiteLLM (supports OpenAI, Ollama, Qianfan, etc.)
- **Vector Operations**: FAISS, NumPy, and will support multiple Vector DB soon
- **Code style**: ruff & mypy (on the way, soon)
- **Key Dependencies**: hugegraph-python-client

## Essential Commands

### Running the Application
```bash
# Install dependencies and create virtual environment (uv already installed)
uv sync
# Activate virtual environment
source .venv/bin/activate
# Launch main RAG demo application
python -m hugegraph_llm.demo.rag_demo.app
# Custom host/port
python -m hugegraph_llm.demo.rag_demo.app --host 127.0.0.1 --port 18001
```

### Testing
```bash
pytest src/tests/
# Or using unittest
python -m unittest discover src/tests/
```
PS: we skip Docker Deployment details here.

## Architecture Overview

### Core Directory Structure
- `src/hugegraph_llm/api/` - FastAPI endpoints (rag_api.py, admin_api.py)
- `src/hugegraph_llm/demo/rag_demo/` - Main Gradio UI application
- `src/hugegraph_llm/operators/` - Core processing pipelines
- `src/hugegraph_llm/models/` - LLM, embedding, reranker implementations
- `src/hugegraph_llm/indices/` - Vector and graph indexing
- `src/hugegraph_llm/config/` - Configuration management
- `src/hugegraph_llm/utils/` - Utilities, logging, decorators

### Key Processing Pipelines

1. **KG Construction** (`operators/kg_construction_task.py`)
   - Text chunking and vectorization pipeline
   - Schema management and validation
   - Information extraction using LLMs
   - Graph data commitment to HugeGraph

2. **Graph RAG** (`operators/graph_rag_task.py`)
   - Multi-modal retrieval (vector, graph, hybrid)
   - Keyword extraction and entity matching
   - Graph traversal and Gremlin query generation
   - Result merging and reranking

3. **Text2Gremlin** (`operators/gremlin_generate_task.py`)
   - Natural language to Gremlin query conversion
   - Template-based and few-shot learning approaches

### Configuration Management

- Main config: `.env` file (generate with `config.generate` module)
- Prompt config: `src/hugegraph_llm/resources/demo/config_prompt.yaml`
- HugeGraph connection settings in environment variables
- LLM provider configuration through `LiteLLM` & `openai/ollama` client

## Development Workflow

1. **Prerequisites**: Ensure HugeGraph Server is running and LLM provider is configured
2. **Environment Setup**: Use UV for dependency management, activate virtual environment
3. **Configuration**: Generate configs and set up .env file with proper credentials
4. **Development**: Use Gradio demo for interactive testing, FastAPI for programmatic access
5. **Testing**: Unit tests use standard unittest framework in src/tests/

## Important Notes

- Always use `uv` package manager instead of `pip` for dependency management
- HugeGraph Server must be accessible while running the app
- The system supports multiple LLM providers through `LiteLLM` abstraction
- Each file should be better < 600 lines for maintainability
