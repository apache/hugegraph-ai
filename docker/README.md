# LLM application image

The image uses Python 3.12. Use `--build-arg PYTHON_VERSION=3.13` or `3.14` to select
another supported runtime. Build from the repository root so it includes the
application, Python client, and the [HugeGraph-LLM SDK](../hugegraph-llm-sdk/README.md) and
[HugeGraph-LLM Eval](../hugegraph-llm-sdk/eval/README.md) workspace packages:

```bash
docker build -f docker/Dockerfile.llm -t hugegraph/rag:local .
docker run --rm --name hugegraph-llm -p 127.0.0.1:8001:8001 hugegraph/rag:local
```

The default command starts the FastAPI application and Gradio interface at
<http://127.0.0.1:8001/>. Configure model and graph connections in the interface
or supply their environment variables when starting the container. The image
does not copy local `.env` files or saved prompts into its build context.
The build compiles `pycgraph` 3.2.2 from a pinned source commit because its
published x86_64 wheel requires a newer C++ runtime than the Bookworm image.

The application depends on the sibling `hugegraph-llm-sdk/` package. External
Python projects can install that SDK directly without Docker or the application;
its current standalone capabilities are schema design, validation, and reviewed
property-graph extraction.

If the build uses a TLS-inspecting proxy, provide a CA bundle as a BuildKit
secret. The bundle must trust the proxy and the public package repositories:

```bash
docker build -f docker/Dockerfile.llm -t hugegraph/rag:local \
  --secret id=proxy_ca,src=/absolute/path/ca-bundle.pem .
```

The secret is available only during dependency installation and is not copied
into the image. Standard Docker `HTTP_PROXY` / `HTTPS_PROXY` build arguments can
be supplied separately when required by the build environment.

## Application smoke test

The smoke test starts a local OpenAI-compatible HTTP fixture **inside an already
running application container**. It uses synthetic credentials and inline graph
schemas, so no model provider or HugeGraph server is required. Use a disposable
container: the test changes its LLM configuration through `/config/llm`.

```bash
docker run --rm -d --name llm-smoke -p 127.0.0.1:8001:8001 \
  -e ENABLE_LOGIN=false \
  -e GRAPH_URL=http://127.0.0.1:9 \
  -e GRADIO_ANALYTICS_ENABLED=false \
  -e LITELLM_LOCAL_MODEL_COST_MAP=True \
  -e OPENAI_API_KEY=local-smoke-no-secret \
  -e OPENAI_EMBEDDING_API_KEY=local-smoke-no-secret \
  -e NO_PROXY=127.0.0.1,localhost \
  -e NLTK_DATA=/home/work/hugegraph-llm/src/hugegraph_llm/resources/nltk_data \
  -e HUGEGRAPH_LLM_ENV_PATH=/tmp/llm-smoke.env \
  -e HUGEGRAPH_LLM_PROMPT_CONFIG_PATH=/tmp/llm-smoke-prompts.yaml \
  hugegraph/rag:local
docker cp docker/tests/smoke_llm.py llm-smoke:/tmp/smoke_llm.py
docker exec llm-smoke python /tmp/smoke_llm.py
docker stop llm-smoke
```

The script waits for startup and exits unsuccessfully if any check fails. A
successful run prints JSON with `"status": "passed"`. It verifies:

- The normal Gradio homepage responds over HTTP.
- The installed HugeGraph-LLM SDK designs and validates a schema using the real OpenAI client
  transport. Schema design currently has no dedicated application HTTP route.
- `/graph/extract` preserves the legacy extraction response without review.
- `/graph/extract` with `review_options={}` performs extraction, review, repair,
  and a second review, returning the corrected graph and per-chunk counters.
- Vertex IDs and relationship endpoints are normalized consistently.

This checks image packaging, imports, provider HTTP wiring, API behavior, and
review orchestration against deterministic responses. It does not measure a real
model's schema or extraction quality, and it does not test graph persistence or
retrieval. On failure, inspect `docker logs llm-smoke` before stopping it.
