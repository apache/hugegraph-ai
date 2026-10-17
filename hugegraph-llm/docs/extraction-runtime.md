# Reviewed Property-Graph Extraction

The first version adds optional model review and repair to the existing
`POST /graph/extract` path. Requests without `review_options`, or with it set to
`null`, keep the existing extraction behavior. Sending an object enables review;
`{}` selects the defaults.

The reviewed path uses the existing configured chat model for extraction, review,
and repair. It validates the graph against the supplied schema and returns a
result for every chunk. It does not write graphs to HugeGraph.

For OpenAI and LiteLLM, our client wrappers omit `max_tokens` from the SDK call
in all three stages. SDK provider adapters and services may still apply default
output limits or hard output and context limits. Existing requests without review
and other model uses retain their configured token limit.

## Setup and a runnable example

Use Python 3.10 or 3.11 and run from the repository root:

```bash
uv sync --python 3.11 --extra llm --extra dev
```

Configure a supported chat model using the existing
[LLM configuration](../config.md). The example uses the same
`get_chat_llm(llm_settings, limit_output=False, raise_on_truncation=True)`
client factory as the extraction node, so it requires a reachable configured
model and any credentials needed by that model. An inline schema avoids a
HugeGraph Server connection.

Run the [Python example](examples/reviewed_property_graph.py):

```bash
uv run --no-sync python hugegraph-llm/docs/examples/reviewed_property_graph.py
```

It runs two text chunks concurrently using the complete inline schema in
[reviewed-extraction.json](examples/reviewed-extraction.json), creates a separate
client for each chunk, and prints all chunk results. Inspect their `status`,
`issues`, and call counts; a successful process exit alone does not mean every
chunk was accepted. Live model outputs and review decisions can vary.

To use the HTTP entry, start the existing service:

```bash
uv run --no-sync python -m hugegraph_llm.demo.rag_demo.app
```

Then send the same example request from the repository root:

```bash
curl -X POST http://127.0.0.1:8001/graph/extract \
  -H 'Content-Type: application/json' \
  --data-binary @hugegraph-llm/docs/examples/reviewed-extraction.json
```

On Windows PowerShell, use `curl.exe` and place the command on one line. The
request contains `texts`, an inline `schema`, and:

```json
"review_options": {"max_reviews": 2, "max_fixes": 1, "max_workers": 2}
```

The supplied schema defines person and company vertices with `name` primary keys,
and `works_for` edges from person to company. It does not need to be installed in
HugeGraph. Existing named-schema requests still use `client_config`.

## Processing and budgets

Each chunk follows:

```text
extract -> validate -> review
              ^           |
              |           +-- pass  -> final
              |           +-- block -> blocked
              +-- repair <- fix
```

Validation checks graph structure, labels, properties, schema-provided types and
required fields, vertex identity, and relation endpoints. Invalid entries are
retained so the model can repair them. Review compares the current graph with the
original text and schema for unsupported facts, wrong properties, relation
direction, and clear omissions. The existing extraction prompt is reused; review
and repair prompts live in `PromptConfig` alongside it.

Repair returns a complete replacement graph. The engine discards old issues,
validates the replacement, and reviews it again when budget remains. Model or
JSON parsing errors fail that chunk instead of being converted into an empty
successful graph. An actual empty graph can pass if validation and review accept
it.

| Option | Default | Accepted range | Meaning |
| --- | --- | --- | --- |
| `max_reviews` | 2 | 0–5 | Maximum review attempts per chunk. |
| `max_fixes` | 1 | 0–3 | Maximum repair attempts per chunk. |
| `max_workers` | 4 | 1–8 | Maximum chunks being prepared or executed concurrently. |

All options require integers; booleans, fractional numbers, and numeric strings
are rejected. Unknown keys, such as `max_review`, and out-of-range values return
HTTP 422 before extraction starts. An empty object selects the defaults.
`max_reviews=0` skips model review but still runs extraction, validation, and any
needed repair within `max_fixes`. No chunk can become `final` without passing
review: valid graphs remain `candidate`, the aggregate `status` is `failed`, and
`result.vertices/edges` are empty. Extracted graphs remain available in
`chunk_results` for inspection. To use legacy extraction without review, omit
`review_options` or set it to `null`; zero is not a switch to the legacy path.
`max_fixes=0` disables repair only. Failed review and repair calls still
consume an attempt. Validation does not consume model budget. The engine makes at most
`1 + max_reviews + max_fixes` model calls per chunk: four with the defaults and
nine at the maximum settings. This counts calls to the existing client, not its
internal transport retries. No additional engine retry layer is added. Worker
limits apply per request, not across all requests. These limits do not cap output
tokens or the total number of chunks.

## Reading responses

The HTTP response retains `status`, `result`, `warnings`, and `meta`. Reviewed
requests also return `chunk_results`, even when `include_meta` is false. Each
chunk result contains:

- `index`, `status`, and the latest `graph` (or `null` if extraction failed).
- Current `issues` with `path`, `message`, and optional source `evidence`.
- `reason`, and a failure `stage` when applicable.
- `reviews_used`, `fixes_used`, and `llm_calls`, including failed attempts.

| Chunk status | Meaning |
| --- | --- |
| `final` | The current graph passed validation and review. |
| `candidate` | Validation passed, but review could not finish or its requested repair exceeded the budget. |
| `blocked` | Validation could not pass within the repair budget, or review explicitly blocked acceptance. |
| `failed` | Preparation, model execution, parsing, or another stage raised an exception. |

Only `final` graphs are concatenated into `result.vertices` and `result.edges`,
in input order. Other graphs and their issues remain in `chunk_results`. The
aggregate status is `succeeded` when all chunks are final, `partial` when some
are final, and `failed` when none are final. A valid reviewed empty graph can be
final; entity count is not a success test.

A completed request returns HTTP 200 even with candidate, blocked, or failed
chunks. Invalid request data returns 422. Request-level schema preparation or
scheduler errors retain the existing error path. An input producing no chunks
is an error in the HTTP path. Old requests omit `chunk_results`.

If an OpenAI or LiteLLM response reports `finish_reason=length`, or an Ollama
response reports `done_reason=length`, that chunk fails before parsing incomplete
output. Its `stage` identifies `extract`, `review`, or `repair`, and its `reason`
is `<stage>_output_truncated: finish_reason=length` or the corresponding
`done_reason=length` form for Ollama.
Review and repair failures preserve the most recent graph; extraction failure
has no graph yet. The failed attempt is counted normally, and truncation does
not add an automatic retry. This reports truncation even when our wrapper omits
`max_tokens`; an SDK provider adapter or the service may still apply an output
limit. Reviewed extraction explicitly enables `raise_on_truncation`; ordinary
clients keep the default `False` and preserve their existing truncated-content
behavior. In the reviewed path, OpenAI bad-request and authentication errors
retain their exception types in the stage failure reason instead of becoming
JSON parsing errors. Ordinary clients preserve their existing error-return
behavior.

## Python integration and concurrency

The concrete domain is `PropertyGraphBundle(llm=..., schema=..., example_prompt=...)`.
The core surface is exported from `hugegraph_llm.extraction_runtime.v1`:
`ChunkInput`, `ExtractionOptions`, `Issue`, `ReviewResult`, `ChunkResult`,
`ExtractionBundle`, `ExtractionEngineV1`, and `run_chunks_v1`.

`run_chunks_v1(chunks=..., prepare=..., options=...)` accepts a finite iterable.
Its factory returns a fresh bundle for each chunk and runs inside the worker
limit. Results are a tuple in input order, regardless of chunk indices or
completion order. Preparation failure becomes a failed chunk; input iteration
errors propagate after running workers finish. Empty Python batches return an
empty tuple. The full batch is retained in memory.

The domain interface has four methods: `extract(chunk)`,
`validate(graph, chunk)`, `review(graph, chunk)`, and
`repair(graph, chunk, issues)`. Validation may normalize IDs and endpoints on the
chunk's own graph, but must keep invalid entries available for repair. Bundle
state and model clients belong to a single chunk. Workers never mutate shared
workflow state; the extraction node assembles the results after the batch ends.
Before dispatching chunks, the node takes one deep snapshot of the current chat
configuration. Every chunk and stage uses that snapshot, so a concurrent UI or
HTTP configuration update applies to subsequent requests. Snapshot creation and
LLM configuration updates share a lock; model execution does not hold it. A new
snapshot waits for an in-progress configuration update, including its connection
check, to finish. The same runtime lock also protects graph configuration and
validated index refreshes; these operations can delay a new snapshot.

## Verification and limits

Run deterministic runtime tests, then the existing API and pipeline regressions:

```bash
uv run --no-sync pytest hugegraph-llm/src/tests/extraction_runtime -q
```

The focused tests exercise the actual engine with scripted domains and the
property-graph parser and validator with fixed model responses. API integration
tests exercise the request/flow/node return chain. These tests do not establish
live-model extraction quality; use the configured-model example for a smoke test.

The first version does not include cross-chunk entity disambiguation, semantic
merge, graph writes, durable jobs, resumable runs, fingerprints, graph version
chains, a generic provider adaptation layer, or a separate final gate. Results
are returned in memory for the caller to inspect and use.
