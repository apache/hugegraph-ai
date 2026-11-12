# hugegraph-llm-eval

An installable evaluation SDK for GraphRAG pipelines and external Python projects.

It is the measurement layer of the project: retrieval, answer and property-graph
scoring rules live here, while `hugegraph-llm` keeps the pipeline, persistence and
reports. Callers provide inputs, inject a judge model only when a metric needs one,
and receive structured records that can be stored elsewhere or fed back into a
repair loop.

## Install

This package ships with the repository and has not been published to a public
index by this change. Use an editable install or a built wheel:

```bash
# in your own project, with the path replaced by the actual checkout
uv add --editable /absolute/path/hugegraph-ai/graphrag/eval

# or build a wheel and install it
uv build --no-sources /absolute/path/hugegraph-ai/graphrag/eval --out-dir /tmp/llm-eval-dist
uv add /tmp/llm-eval-dist/hugegraph_llm_eval-1.8.0-py3-none-any.whl
```

Optional extras add vendor-specific metrics and transports:

| Extra | Adds |
| --- | --- |
| `graph` | semantic entity and triple matching (`networkx`) |
| `rouge` | ROUGE-L answer scoring (`rouge-score`, `jieba`) |
| `openai` | OpenAI-compatible judge transport (`openai`) |

`ClaudeCodeJudge` and `CodexAppServerJudge` need no extra; they drive the `claude`
or `codex` CLI found on `PATH`.

The base install depends on Pydantic only. Python 3.12–3.14 are supported.

## Quick start

No judge model is needed for ranking metrics:

```python
from hugegraph_llm_eval import (
    InMemoryArtifactStore,
    MRREvaluator,
    RecallAtKEvaluator,
    evaluate,
    retrieval_input,
)
from hugegraph_llm_eval.integrations.retrieval.materializers import RetrievalArtifactMaterializer
from hugegraph_llm_eval.utils.clock import utc_now

store = InMemoryArtifactStore()
evaluation_input = retrieval_input(
    store,
    candidate_doc_ids=["doc-b", "doc-a"],
    reference_doc_ids=["doc-a"],
)
materializer = RetrievalArtifactMaterializer(store)

result = evaluate(
    [RecallAtKEvaluator(materializer, k_values=(1, 3), clock=utc_now), MRREvaluator(materializer, clock=utc_now)],
    evaluation_input,
)
for record in result.records:
    print(record.invocation_key, [(m.name, m.value) for m in record.measurements])
```

## Run every metric

[`examples/all_metrics.py`](examples/all_metrics.py) exercises all sixteen metrics and both
entry points in one run. It uses a deterministic stand-in judge unless a model is
configured, so it runs without an API key:

```bash
uv add --editable /absolute/path/hugegraph-ai/graphrag/eval --extra graph --extra rouge
python examples/all_metrics.py

# same script against a real model
EVAL_JUDGE_MODEL=<model> EVAL_JUDGE_API_KEY=<key> python examples/all_metrics.py
```

| Group | Metrics |
| --- | --- |
| Retrieval | `recall@k`, `hit@k` (any/all), `MRR`, context precision, context relevancy, context entity recall, evidence recall |
| Answers | ROUGE-L (English and Chinese), answer correctness, factual correctness, faithfulness, noise sensitivity |
| Graph extraction | entity extraction precision/recall/F1, relation extraction precision, recall and F1, schema validity, graph faithfulness |

Entity and relation scores compare the candidate graph against a reference graph and
match semantically: equivalent names may match despite label or property differences,
which are reported as issues. Different entity meanings, incompatible relation
endpoints or reversed directions prevent a match. Schema validity and graph
faithfulness score the candidate graph on its own, against the declared schema and the
source text.

### Scoring boundaries

- Semantic entity/triple judges propose every valid candidate/reference pair in
  each bounded candidate/reference window, including alternatives for the same
  item. A reference with no match in that window gets one null verdict. The
  default `matching_strategy="max_weight"` selects a maximum-total-weight
  one-to-one assignment over **all returned pairs**. Set `"max_cardinality"` on
  either semantic evaluator to maximize matched count first, then weight. The
  strategy changes the evaluator digest. For weights 100 versus two compatible
  edges of 49 each, the default deliberately chooses one match; cardinality mode
  chooses two. Custom prompts and judges must propose alternatives, never assign
  locally. Neither strategy guarantees an LLM finds every true semantic pair.
- Schema validity checks the declared basic contract: vertex labels, primary-key
  presence and per-label composite-key uniqueness, edge labels and actual endpoint
  types. It is **not** a complete HugeGraph database-schema validator: property
  data types, undeclared properties and edge sort keys are not represented here.
  Primary-key values retain their case and JSON type. An explicit endpoint label
  disambiguates equal names; without it, a name must resolve to exactly one type.
  Invalid graphs produce findings rather than failing input construction.
- Context entity recall freezes an entity inventory before judging coverage.
  Supply `reference_entities` to `retrieval_input` for an authoritative denominator;
  otherwise a separate extraction call sees only the reference answer, not the
  retrieved contexts. Coverage must return every inventory item unchanged, including
  missing entities. Omitted, renamed or out-of-window items fail the metric rather
  than inflate recall. An empty inventory is `not_applicable`, not a perfect score.
  Model-extracted inventories can still omit entities; fixing the inventory does
  not turn an LLM extraction into ground truth. Entity text is retained in findings.
- Judged answer metrics treat `references` as cumulative reference content.
  ROUGE-L instead selects the best lexical reference. For alternative correct
  answers, evaluate the alternatives separately and choose an aggregation in the
  calling application. Factual correctness counts decomposed claims, so repeated
  or differently split claims can change their weight; it does not deduplicate
  unique facts.
- `noise_sensitivity` measures incorrect answer claims attributed to contexts that
  also support reference claims (the **relevant-context** mode). It does not
  measure all errors caused by irrelevant contexts or regenerate an answer after
  removing context. A zero score alone therefore does not establish robustness
  to irrelevant noise.
- Claim findings retain the judged text in `evidence.description`. Claims longer
  than 2,000 characters have an explicit `… [truncated]` preview; generated
  `statement-N` locators identify this evaluation's claims, not offsets in the
  original answer. Full provider outputs are not persisted by this package.

## Batch API

Run several metrics with ordering, bounded concurrency, retries, deadline and
cancellation applied by the engine:

```python
from hugegraph_llm_eval import EvaluationOptions, evaluate

result = evaluate(
    [recall, mrr, semantic_entity],
    evaluation_input,
    options=EvaluationOptions(request_key="case-1", max_concurrency=4, max_attempts=2),
)
print(result.status, [record.status for record in result.records])
```

`status` is `completed`, `partial`, `failed` or `cancelled`; record-level failures
stay in the result instead of raising.

Cancellation is cooperative: it prevents work that has not started, including
judge calls waiting for a concurrency slot, but does not interrupt a synchronous
judge call already in progress. Cancelling `aevaluate` or `aevaluate_many`
signals the underlying run and returns cancellation to the caller; an in-flight
provider call can continue and incur usage until it finishes or times out. Set a
deadline or provider timeout to bound that wait.

For the Codex app-server judge, an interruption after the turn ID is known
requests that the turn stop. If interruption or timeout occurs while the
`turn/start` response is still pending, the turn ID is unavailable and the
provider may continue processing; interruption is best-effort. A timed-out or
disconnected start with an unknown outcome is not automatically retried, to
avoid starting another potentially billable turn. A timeout or connection loss
while waiting for an active turn is also not automatically retried, because a
stop request may not have been confirmed.

Two knobs bound the work, and both have a hard upper bound of 8:

| Option | Bounds |
| --- | --- |
| `max_concurrency` | evaluators running inside one input |
| `max_samples` | inputs running at once in `evaluate_many` |

Every sample and metric of one call shares a single provider limit of
`max_samples × max_concurrency` concurrent judge calls, and a single
`budget_usd`. Nested work — such as the candidate batches of a semantic
matcher — waits on that same limit instead of multiplying it:

```python
results = evaluate_many(
    [recall, mrr, semantic_entity],
    inputs,
    options=EvaluationOptions(request_key="batch", max_samples=4, max_concurrency=4),
)
```

Defaults are deliberately conservative: one sample, one metric, three provider
attempts. Batch workloads usually set both concurrency values explicitly, and
the per-call limiter keeps the total provider concurrency at their product.

`budget_usd` is settled when an evaluator finishes, so it is a scheduling guard,
not a hard cap on an in-flight multi-step evaluator. Known costs are summed over
`judge_calls[].provenance.attempts`, including billed attempts whose outputs failed
validation. `judge_calls[].usage` describes the final successful response and must
not be added again. Unknown or unpriced attempts stop later samples and metrics
in a budgeted run while preserving completed records. With `openai_judge`, supply
both `input_usd_per_million` and `output_usd_per_million` for cost estimates; a
provider must also report usage for its cost to be verifiable.

### Large inputs and per-request limits

Judged evaluators accept an optional `batching=BatchingOptions(...)`:

```python
from hugegraph_llm_eval import BatchingOptions, GraphFaithfulnessEvaluator

metric = GraphFaithfulnessEvaluator(
    materializer,
    judge=judge,
    prompt=prompt,
    rubric=rubric,
    clock=utc_now,
    batching=BatchingOptions(max_items=128, max_payload_bytes=128_000),
)
```

Defaults are 256 items and 512,000 UTF-8 JSON payload bytes. Graph faithfulness
batches vertices and edges with global indices; semantic matching windows both
candidate and reference collections and then applies one global assignment.
Context precision/relevancy, evidence/entity coverage and answer NLI verification
also batch items. Context precision is calculated over the complete original
ranking, **not** averaged across per-window precision scores. All calls retain
the shared limiter, deadline, cancellation and attempt-level usage accounting.

Shared evidence is copied intact into each request, never silently truncated.
Answer decomposition and global correctness classification remain whole-input
operations because arbitrary splitting would change their semantics. If a single
item plus shared evidence, or a whole-input task, exceeds the byte limit, the
record fails with `evaluation_payload_too_large`; previous call provenance is
kept and an incomplete metric is not reported as a complete score. Split the
business input meaningfully or explicitly adjust the limit.

These are **payload** limits, not model context-token or output-token limits:
system prompts, schemas and model tokenization have additional overhead. Dense
semantic alternatives can still exceed a provider's output limit. Smaller windows
increase call counts; two-sided semantic batching has a candidate-window ×
reference-window cost. Budget settlement remains evaluator-level, so `budget_usd`
is not a hard per-request spending ceiling. Configure provider-specific limits
and bound workloads with a deadline.

The context-entity Judge protocol now includes `ReferenceEntitiesOutput` followed
by coverage requests containing a fixed `entities` list. Custom Judge adapters
must support both response types, or callers can pass `reference_entities` to
skip extraction. Empty and omitted inventories are intentionally distinct.

## Judge-based metrics with a real model

Any OpenAI-compatible endpoint works. `openai_judge` builds the transport, and
`max_attempts` bounds provider attempts per Judge call. Multi-step metrics can
make several Judge calls:

```python
from hugegraph_llm_eval import (
    GraphFaithfulnessEvaluator,
    JudgeContent,
    evaluate,
    graph_review_input,
    openai_judge,
)
from hugegraph_llm_eval.integrations.graph_extraction.materializers import GraphArtifactMaterializer
from hugegraph_llm_eval.prompt import graph_judge_prompt, graph_judge_rubric

judge = openai_judge(model="your-model", api_key="...", base_url="https://your-gateway/v1")
evaluation_input = graph_review_input(store, candidate=candidate, source_text=source, schema=schema)
materializer = GraphArtifactMaterializer(store)
evaluator = GraphFaithfulnessEvaluator(
    materializer,
    judge=judge,
    prompt=JudgeContent(component=prompt_ref, text=graph_judge_prompt("faithfulness", "en")),
    rubric=JudgeContent(component=rubric_ref, text=graph_judge_rubric("faithfulness", "en")),
    clock=utc_now,
)
result = evaluate([evaluator], evaluation_input, options=EvaluationOptions(request_key="case-1"))
```

A complete runnable version is in [`examples/real_model.py`](examples/real_model.py):

```bash
export EVAL_JUDGE_MODEL=<model>
export EVAL_JUDGE_API_KEY=<key>
# export EVAL_JUDGE_BASE_URL=<gateway>   # optional
# export EVAL_JUDGE_PROVIDER=<provider>  # optional, labels the judge descriptor
python examples/real_model.py
```

It scores a small property graph against its source text and prints the
measurements plus each unsupported item. Without configuration it explains what
to set and exits with code 2.

## Judges on a Claude or Codex subscription

Two judges run on a logged-in coding-agent CLI instead of an API key. Both plug in
wherever `openai_judge` does:

```python
from hugegraph_llm_eval import ClaudeCodeJudge, CodexAppServerJudge

judge = ClaudeCodeJudge(model="sonnet")  # inherits the CLI's current authentication

# Force the local Claude subscription instead of ambient API credentials:
judge = ClaudeCodeJudge(model="sonnet", auth_mode="subscription")

with CodexAppServerJudge(model="<a model your account can use>", effort="low", auth_mode="subscription") as judge:
    ...  # one shared `codex app-server` process, one ephemeral thread per call
```

| | `ClaudeCodeJudge` | `CodexAppServerJudge` |
| --- | --- | --- |
| Authentication | `claude` login or `CLAUDE_CODE_OAUTH_TOKEN` | `codex` ChatGPT login; `auth_mode="subscription"` fails unless the app-server reports a ChatGPT account |
| Process | one `claude -p` per call | one long-lived `codex app-server`, started on first use |
| Concurrency | any | calls share the process; the shared limiter still bounds them |
| Cleanup | none | `close()`, a `with` block, or interpreter exit |
| Structured output | `--json-schema` | `outputSchema` (OpenAI strict mode, derived from the response model) |

What to know before using them:

- **Same login as your terminal.** `ClaudeCodeJudge` starts `claude -p` with your
  environment and settings, so it uses whatever `claude` is signed in to: a
  subscription login, `CLAUDE_CODE_OAUTH_TOKEN`, or a gateway from
  `~/.claude/settings.json`. An exported `ANTHROPIC_API_KEY` is billed to the API, not
  to the subscription: in `-p` mode a present key is always used
  ([authentication precedence](https://code.claude.com/docs/en/authentication#authentication-precedence)).
  To force the subscription, use `auth_mode="subscription"`:
  that removes `ANTHROPIC_*` and `CLAUDE_CODE_USE_*` from the child environment and
  ignores settings files. Before the first evaluation call it runs `claude auth status`
  and only accepts `authMethod` values `claude.ai` or `oauth_token`; missing login,
  API-key auth, or an unreadable status fail closed (`provider_not_authenticated`,
  `provider_account_not_subscription`, or `provider_auth_status_unavailable`). The
  lower-level `scrub_provider_env=True, setting_sources=""` combination remains
  available for compatibility.
- **No user hooks or tools.** Claude runs with `--tools ""` and does not support raw
  `extra_args`. Codex runs ephemeral and read-only, with approvals off and shell, apps,
  plugins and user MCP servers disabled. Each Codex judge gets a private `CODEX_HOME`:
  only the file-backed `auth.json` is copied from the user home (with owner-only
  permissions); `hooks.json`, `config.toml`, skills and plugins are not inherited.
  This prevents user-global Codex hooks from executing during evaluation. Keyring-only
  Codex authentication is not copied into the isolated home; use file-backed login or
  an environment credential with `auth_mode="inherit"`. If Codex cannot read the
  effective MCP configuration, the judge fails closed instead of continuing without
  verifying isolation.
- **Tokens, not cost.** Both report token counts and leave `cost_usd` empty. With
  `budget_usd` set, that unknown cost stops later samples and metrics, so leave the
  budget unset and bound a subscription run with `max_samples`, `max_concurrency` and
  a deadline.
- **Not reproducible.** Neither CLI exposes temperature or seed, and each call carries
  the CLI's own prompt overhead (roughly 5K input tokens for Claude, 11K for Codex).
  The CLI version, effort and isolation settings are part of the judge descriptor, so
  results from different versions are distinguishable.
- **Usage limits.** A subscription limit surfaces as the permanent failure
  `provider_usage_limit` and is not retried.
- **Codex needs an explicit `model`**; the account default may be unavailable to
  app-server clients. `auth_mode="inherit"` (default) uses whatever login the CLI has.
  `auth_mode="subscription"` reads `account/read` once at startup and fails with the
  permanent `provider_not_authenticated` (no login) or `provider_account_not_chatgpt`
  (logged in with an API key) instead of billing an API key; it also removes
  `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_ORG_ID` and `OPENAI_PROJECT_ID` from the
  child process. OpenAI recommends API keys for automation such as CI/CD
  ([Codex authentication](https://developers.openai.com/codex/auth)); for API-key
  billing use `openai_judge(...)` with an explicit key and endpoint.

## Input builders

| Helper | Input schema | Metrics |
| --- | --- | --- |
| `answer_input` | answer / references / question + contexts | ROUGE-L, answer correctness, factual correctness, faithfulness, noise sensitivity |
| `retrieval_input` | candidate and reference doc ids, optional question for ranking | recall@k, hit@k, MRR, context precision/relevancy, entity and evidence recall |
| `graph_review_input` | candidate graph + source text + schema | schema validity, graph faithfulness |
| `graph_extraction_input` | candidate + reference + source + schema | entity/relation extraction precision, recall and F1, schema validity, graph faithfulness |

For ranking metrics, `retrieval_input` needs only document ids. Judge-based
retrieval metrics require a non-empty question and reject a missing question
before making a provider call.

## Design boundary

| In this package | Stays in the calling application |
| --- | --- |
| Domain contracts and ports | Databases, artifact stores and file layout |
| Evaluators and judge protocol | Vendor SDK configuration and credentials |
| Concurrency, retry and cancellation semantics | CLI, web UI and report rendering |
| Structured findings usable as repair input | Product-specific pipeline adapters |

The core must not import application configuration, UI, graph clients or logging
initialization. Vendor dependencies are imported only when the corresponding
extra is installed.
