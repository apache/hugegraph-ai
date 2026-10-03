# Experimental Extraction Runtime

`hugegraph_llm.extraction_runtime` is a dormant, experimental internal subsystem
for domain-neutral extraction of already-normalized chunks. Its single-chunk
engine can also run in concurrent batches with independent per-chunk state.
It is not a replacement for `GraphExtractFlow`, a public extension API, or a
production route.

For component responsibilities, the review/repair lifecycle, and extension boundaries,
see the [architecture explanation (中文)](extraction-runtime-architecture.zh-CN.md).

## Boundary

The versioned runtime executes this fixed lifecycle:

```text
extract -> schema -> identity -> bounded review/fix -> final gate
```

The runtime owns the current immutable graph revision, business review/fix
budget accounting, trace, diagnostics, terminal resolution, layered
fingerprints, and an uncommitted terminal artifact body. A statically supplied
Bundle owns every domain-specific prompt, schema, identity rule, review/fix
policy, materializer, and final gate.

The provider package defines credential-free neutral and effective request
contracts, capability adaptation records, and a deterministic ReplayProvider.
It does not modify or wrap the existing OpenAI, Ollama, or LiteLLM clients.

## Experimental use

Use a checkout containing this module and Python 3.10 or 3.11. From the repository
root, install the workspace and test dependencies:

```bash
uv sync --python 3.11 --extra llm --extra dev
```

The replay example and runtime tests need neither a running HugeGraph Server nor
model credentials. They verify the execution protocol using fixed responses;
they do not measure extraction quality from a live model.

Repository-internal experiments may import the versioned surface explicitly:

```python
from hugegraph_llm.extraction_runtime.v1 import ExtractionEngineV1
```

The Inventory Bundle in `hugegraph_llm.extraction_runtime.conformance` is a
deterministic inventory fixture that demonstrates the complete lifecycle. It is
not a stable Bundle API promise or a production domain.

## Concurrent chunks

`run_chunks_v1(chunks=..., prepare=..., max_workers=4)` runs a finite batch
through the existing single-chunk engine. `prepare(chunk)` returns a fresh
Bundle and its `RunControlV1`. It runs in a worker thread, so create a separate
stateful Provider for each chunk, and synchronize any external mutable state
shared by the factory itself. In particular, do not share a ReplayProvider's
transcript cursor between chunks.

The worker limit covers preparation and the entire extract/review/fix lifecycle.
Budgets apply independently to each chunk. Results are a tuple of
`ChunkRunResultV1(chunk, result)` in input order, even if execution completes out
of order. Chunk ordinals do not reorder the results. An empty input returns an
empty tuple; `max_workers=1` runs serially.

The batch preserves each engine result, including `failed`, `blocked`, and
`candidate`, so one extraction failure does not discard successful chunks.
Errors while preparing a Bundle or iterating the input propagate to the caller;
they do not become extraction artifacts. Running tasks finish and the thread
pool closes before the call returns or raises. A preparation error may cancel
tasks that have not started.

This synchronous helper submits and retains the whole batch in memory. It does
not merge graphs or resolve identities across chunks. Concurrency does not
change a chunk's semantic fingerprint; deterministic replay produces the same
artifact when run serially or concurrently.

After the setup above, save this example as `extraction_example.py` in the
repository root and run `uv run --no-sync python extraction_example.py`.
It uses two fixed replay outputs:

```python
from hugegraph_llm.extraction_runtime.conformance import InventoryBundleV1
from hugegraph_llm.extraction_runtime.provider import (
    ProviderResponseV1,
    ReplayEntryV1,
    ReplayProvider,
)
from hugegraph_llm.extraction_runtime.v1 import (
    NormalizedChunkV1,
    ReviewBudgetV1,
    RunControlV1,
    run_chunks_v1,
)


def prepare(chunk):
    template = InventoryBundleV1(ReplayProvider(()))
    request = template.plan_extract(chunk)
    entry = ReplayEntryV1(
        requested_request_digest=request.adaptation.requested_digest,
        effective_request_digest=request.adaptation.effective_digest,
        response=ProviderResponseV1(
            output={"graph": {"items": [{"sku": chunk.chunk_id, "count": 2}]}},
            model=template.model,
        ),
    )
    bundle = InventoryBundleV1(ReplayProvider((entry,)))
    control = RunControlV1(
        budget=ReviewBudgetV1(max_reviews=2, max_fixes=1),
        provider_execution=bundle.provider_execution(),
    )
    return bundle, control


chunks = [
    NormalizedChunkV1(document_id="stock", chunk_id="BOLT", ordinal=0, text="Two bolts."),
    NormalizedChunkV1(document_id="stock", chunk_id="NUT", ordinal=1, text="Two nuts."),
]
for item in run_chunks_v1(chunks=chunks, prepare=prepare, max_workers=2):
    print(item.chunk.chunk_id, item.result.intent.kind.value)
```

Expected output is `BOLT final` followed by `NUT final`. Replace `prepare` with
your own Bundle and Provider construction to use a different domain or model.

## Reading the result

Each chunk result includes its graph, terminal decision, budget usage, execution
trace, diagnostics, fingerprints, and an uncommitted artifact body. Check the
terminal decision before treating a graph as accepted:

| Terminal | Meaning |
| --- | --- |
| final | The current graph passed validation, identity checks, review, and the final gate. |
| candidate | The graph passed structural and identity checks, but the quality budget ended or the final gate requested a hold. |
| blocked | Required graph checks could not be satisfied within the repair budget, or review or the final gate explicitly blocked acceptance. |
| failed | Execution or result construction failed; a graph may be absent. |

None of these states implies a file was saved or a graph was written to HugeGraph.
The [terminal rules](../src/hugegraph_llm/extraction_runtime/v1/terminal.py) define
the precise mapping and reason codes.

## Extending the prototype

- **Add a domain:** implement the [Bundle contract](../src/hugegraph_llm/extraction_runtime/v1/engine.py),
  using the [Inventory example](../src/hugegraph_llm/extraction_runtime/conformance/inventory.py)
  as a reference. Supply the domain's prompts, graph and identity rules, review,
  repair, and final decision. Declare the resources and rules in the semantic
  manifest so their changes affect the run fingerprint.
- **Add a model connection:** implement the transport in the
  [provider contracts](../src/hugegraph_llm/extraction_runtime/provider/contracts.py)
  and adapt its output to the domain graph. The existing Inventory model name
  and output format are replay fixtures, not a ready-to-use live provider setup.
- **Add application integration:** prepare normalized chunks and own storage,
  recovery, cross-chunk merging, and publication outside the engine. Batch
  preparation must keep stateful Bundle and Provider instances independent.

Repairs return a complete replacement graph bound to the previous graph digest;
review and final decisions must refer to the current graph. Preserve these
relationships when implementing a domain. The
[conformance tests](../src/tests/extraction_runtime/test_inventory_conformance.py)
show a repair cycle, terminal outcomes, and invalid repair cases; use those
behaviors as a starting point for testing a new integration.

## Local verification

After setup, run the runtime suite from the repository root:

```bash
uv run --no-sync pytest hugegraph-llm/src/tests/extraction_runtime -q
```

The suite covers the lifecycle, repaired graph propagation, terminal decisions,
provider adaptation and replay, concurrent state isolation, and separation from
production callers. A successful run ends with all selected tests passing.
These tests belong to the repository's [unit / pure contract layer](../../docs/quality/test-taxonomy.md).
Passing them verifies the prototype's contracts, not live-model quality or a
complete application integration.

## Compatibility and rollback

The package has no production caller. `GraphExtractFlow`, `/graph/extract`, the
fixed-flow scheduler, existing provider clients, and existing defaults remain
unchanged. There is no `/extraction-jobs` route, extraction CLI, durable host
commit, rollout switch, database migration, or HugeGraph write in this version.

Rollback consists of removing the dormant package and its tests. No artifact,
database, or HugeGraph migration is required.
