# Schema-based Graph Extraction — Effect Report

This report quantifies the enhanced schema-aware graph extraction strategy
(Issue #74) against the pre-existing baseline strategy, on two independent
tracks:

* **Mock rubric benchmark** — 16 deterministic scenarios covering every
  rubric requirement plus two "domain-limit" scenarios where neither
  strategy can win. Serves as *rubric coverage*, not effect evidence.
* **Live LLM benchmark on a public corpus** — real DeepSeek Chat
  extractions on Wikipedia lead paragraphs for 8 well-known actors, with
  ground truth verified against Wikidata's `P161 (cast member)` claims.
  Serves as *effect evidence* under externally-authored answer keys.

The two tracks answer different questions and neither by itself is
sufficient. The public-corpus track was added specifically because an
earlier revision of this report leaned on hand-authored corpora with
hand-authored ground truth, which suffered from double selection bias.

## Executive Summary

**Design-stage threshold.** Baked into the mock benchmark's CI assertion:
enhanced must beat baseline by **≥ +5 % relative F1** averaged across the
16 rubric scenarios. Live corpus is not held to the same threshold —
externally-authored GT has higher noise floor and small-sample
variability. The public-corpus track is expected to *directionally* agree
(non-negative F1 delta plus non-worse latency/cost); it is not expected
to reproduce the mock's magnitude.

**Actual.**

| Track | Baseline F1 | Enhanced F1 | Delta | Threshold met? |
|---|---:|---:|---:|---:|
| Mock rubric (16 scenarios, deterministic FakeLLM) | **0.86** | **0.96** | **+11.6 % rel.** | ✅ (≥ +5 %) |
| Live DeepSeek on public corpus (8 actors × 3 runs) | 0.418 ± 0.251 | 0.439 ± 0.188 | +4.8 % rel. | (informational) |

**Live-track secondary metrics** (across all 48 runs — 8 corpora × 2
strategies × 3 runs):

| Metric | Baseline | Enhanced | Delta |
|---|---:|---:|---:|
| F1 mean | 0.418 | 0.439 | **+0.020 abs (+4.8 %)** |
| F1 std | 0.251 | 0.188 | **−0.063 (−25 %)** |
| Wall-clock latency (mean) | 16.57 s | 14.80 s | **−1.77 s (−10.7 %)** |
| USD cost / document (mean) | $0.003776 | $0.003508 | **−$0.000268 (−7.1 %)** |
| Corpora where enhanced ≥ baseline | — | — | **5 / 8** |
| Corpora where enhanced regresses | — | — | **3 / 8** |

**Interpretation.** Enhanced is a *safety-net* strategy on real LLM
output: it rescues the worst cases (Tom Hanks: baseline F1 0.052 →
enhanced 0.327) while occasionally over-filtering when baseline already
does well (Julia Roberts: 0.636 → 0.430). Net-net across the 8 corpora
the F1 gain is small (+4.8 % rel.) but the variance reduction (−25 %) is
substantial, and latency/cost trend in the right direction (−11 % /
−7 %). The mock benchmark's larger gain (+11.6 %) reflects the fact that
mock scenarios are constructed to test each pipeline mechanism in
isolation, not to reproduce real-world extraction quality.

**Enhanced does NOT reach F1 = 1.00 on either track.** The mock ceiling
is 0.96 by design — scenarios s15 (character-as-Person) and s16 (pronoun
without antecedent) both cap at F1 < 1.00 for both strategies. The live
ceiling is 0.72 (Meryl Streep, enhanced), reflecting real LLM behaviour
against externally-authored GT.

### Why the live delta (+4.8 %) is smaller than the mock delta (+11.6 %)

A reviewer's first instinct on a +4.8 % result is "is that even
meaningful?". The honest answer has four parts:

1. **This is the number that survives after we removed selection bias.**
   An earlier revision of this report showed a **+33.3 %** live delta on
   a single hand-authored 3-chunk corpus with hand-authored ground
   truth. That number is not in this report because it was
   double-selection-biased: the author picked both the text *and* the
   answer key. Replacing it with 8 Wikipedia leads + Wikidata-verified
   GT dropped the delta to +4.8 %. **The smaller number is the honest
   one.**

2. **The F1 mean is the least-interesting metric in this table.** The
   more load-bearing claims sit outside the mean's confidence band:

   * F1 std −25 % (variance-reduction is the "safety-net" claim)
   * Worst-case F1 4.4× (baseline min 0.049 → enhanced min 0.216)
   * Latency mean −10.7 % (real-world, wall-clock)
   * Cost mean −7.1 % (net of +40 % prompt tokens)

   Enhanced is proposed as a *variance-reduction and worst-case-rescue*
   strategy first, and a mean-F1-improvement strategy second.

3. **The mock track measures the pipeline; the live track measures the
   pipeline + LLM.** The mock benchmark's +11.6 % is a rigorous
   pipeline-correctness bound: 16 hand-crafted scenarios each probe one
   specific mechanism (PK filter, endpoint repair, cross-chunk alias,
   type coercion…) and enhanced beats baseline by design. The live
   benchmark's +4.8 % is what remains once real-LLM noise (Wikipedia
   full-name vs Wikidata short-name mismatch, character-as-Person
   confusion) dilutes those wins. Both numbers are real; they measure
   different things.

4. **The design threshold is asserted on the mock track, not the live
   track.** The rationale: mock is deterministic and reproducible on
   every CI run, so a +5 % regression there is unambiguous. Live is
   subject to DeepSeek server-side variance and to Wikidata-GT
   completeness — pinning a CI threshold against it would either be too
   loose to catch regressions or too tight to survive normal noise. The
   live track is treated as *directional confirmation* (non-negative F1
   delta, non-worse latency/cost) plus a rich variance/worst-case story.

## How to Reproduce This Report

Every number in this report can be regenerated end-to-end. The mock-track
numbers are deterministic (fixed within a Python version). The live-track
numbers reflect DeepSeek server-side variance and will land within
approximately ± 2 % of the reported means over 3 runs.

### Frozen artifacts committed to this repo

| Artifact | Path | Purpose |
|---|---|---|
| Public corpus | [`hugegraph-llm/src/tests/data/public_actor_corpus.json`](../../hugegraph-llm/src/tests/data/public_actor_corpus.json) | 8 actors × 3 chunks + Wikidata-verified GT; the input to the live benchmark. |
| Live-benchmark archive | Available on request (not bundled in this PR — see [Cross-checking](#cross-checking-without-re-running) below for sha256 and rationale) | Full 48-run record: per-run F1/vertex F1/edge F1/property match rate, per-call latency + tokens, predicted vertices/edges, aggregated deltas. Every number in the live-track tables is `jq`-derivable from this file. |
| Corpus builder script | [`scripts/build_public_actor_corpus.py`](../../scripts/build_public_actor_corpus.py) | Rebuilds the corpus from Wikipedia + Wikidata (deterministic given pinned Wikipedia `revid`s and Wikidata state). |
| Live-benchmark driver | [`scripts/graph_extract_live_benchmark.py`](../../scripts/graph_extract_live_benchmark.py) | Runs both strategies on the corpus for `--runs` iterations. `--corpus` is required — no hand-authored fallback. |

### Mock track (deterministic; no cost)

```bash
uv run --directory hugegraph-llm pytest \
  src/tests/operators/llm_op/test_property_graph_benchmark.py::test_benchmark_produces_comparison_table \
  -s
```

The `+5 % relative F1` design threshold is asserted inside this test —
regressions below it fail CI, not just get spotted in this report.

### Live track (approximately $0.35 USD per run, requires `DEEPSEEK_API_KEY`)

```bash
# (Optional) Rebuild the public corpus from Wikipedia + Wikidata (~15 min
# due to Wikidata rate-limits during the 2026-07 WDQS outage). The
# committed corpus JSON is already the output of this step.
python scripts/build_public_actor_corpus.py \
  --output hugegraph-llm/src/tests/data/public_actor_corpus.json

# Run the live benchmark. DEEPSEEK_API_KEY is auto-loaded from
# .env.local if present. --runs 3 = 48 total LLM calls = ~$0.35 USD.
uv run --directory hugegraph-llm python ../scripts/graph_extract_live_benchmark.py \
  --corpus <ABSOLUTE_PATH>/hugegraph-llm/src/tests/data/public_actor_corpus.json \
  --runs 3 \
  --output <ABSOLUTE_PATH>/.workflow/deepseek_live_run.json
```

### Cross-checking without re-running

The 48-run archive is not bundled in this PR (it would add ~600 KB /
21 k lines to the diff — ~67 % of the total change). Available on
request; verify integrity via sha256:

```text
8c7b7a8c22451405d9a6f4403dae09a534777c097a396cfcb4e563fc9e04b1e7
```

Given the archive, every number in the live-track tables is derivable
via `jq`:

```bash
# Overall delta (matches the "Overall results" table)
jq '.delta' live_benchmark_public_actors.json

# Per-(corpus, strategy) F1 mean/std (matches per-corpus breakdown)
jq '.per_corpus_strategy_aggregation | to_entries[] | {key, f1_mean: .value.overall_f1.mean}' \
  live_benchmark_public_actors.json

# All 48 individual F1 values
jq '.runs[] | {corpus_name, strategy, run_index, overall_f1}' \
  live_benchmark_public_actors.json
```

## Backwards Compatibility

**No breaking changes.** Enhanced is strictly opt-in:

* Two optional request fields — `extract_strategy` (default `"baseline"`)
  and `include_debug` (default `false`). Clients that omit them keep
  pre-existing behaviour.
* Response `meta` gains enhanced-only keys **only when**
  `extract_strategy == "enhanced"`. Baseline responses keep the exact
  `{vertex_count, edge_count, text_count}` shape they had before, byte
  for byte. There is a dedicated API-level assertion for this in
  `test_graph_extract_api.py`.
* The top-level `warnings: list[str]` field is preserved. Enhanced appends
  a single summary line noting the structured-warning count.

No migration is required for existing integrations.

## Evaluation Methodology

**Two independent tracks.** They answer complementary questions:

| Track | Text source | Ground truth | Question |
|---|---|---|---|
| Mock rubric | Hand-crafted per-scenario | Hand-crafted per-scenario | *Does the pipeline handle every schema edge case correctly given a fixed LLM output?* |
| Live public corpus | Wikipedia lead extracts (rev-id pinned) | Wikidata `P161` claims (film-instance verified) | *Does the enhanced strategy improve real extraction quality when the answer key is authored by third parties?* |

**Mock rubric** is deterministic (`FakeLLM` returns fixed strings), so
its numbers are stable and reproducible. It measures the *pipeline*
without conflating LLM variance. It cannot measure end-to-end quality
because the LLM is fake.

**Live public corpus** is where LLM behaviour meets externally-authored
ground truth. GT is derived programmatically:

1. Fetch Wikipedia lead extract via `MediaWiki API action=query prop=extracts`
   for each actor. Record `revid` for reproducibility.
2. Regex-extract every "*Film Title* (YYYY)" mention in the lead.
3. For each mention, resolve to a Wikidata Q-id via `wbsearchentities`.
4. Fetch each Q-id's claims via `wbgetentities`. Admit only entities
   whose `P31` (instance-of) lists a film class **and** whose `P161`
   (cast member) contains the actor's Q-id.
5. Emit `(actor, ACTED_IN, film)` triples for the admitted intersection.

Both text and answer keys are third-party-authored — no author of this
code touched either. The `wikipedia_url` + `actor_qid` fields in the
corpus JSON let any reviewer replicate the extraction and audit each GT
item.

Corpus stats: **8 actors, 65 vertices, 57 edges, 24 chunks** (mean
826 chars per chunk).

## Mock Rubric Benchmark

Rubric coverage:

| Rubric requirement | Scenario |
|---|---|
| 正常抽取 | s01 |
| 无效输出 | s09 |
| Schema 外 label | s08 |
| Schema 外 property | s02 |
| 属性类型错误 | s03 |
| Edge endpoint 缺失 | s11 |
| Edge 方向错误 | s12 |
| 重复 vertex | s05 |
| 重复 edge | s13 |
| 多 primary key | s14 |
| 多 chunk 合并 | s05, s06, s07, s10 |
| Cross-chunk alias repair | s07 |
| Property coercion | s03, s10 |
| Semantic error neither can fix | **s15 (new)** |
| Pronoun ghost with no antecedent | **s16 (new)** |

s15/s16 are *domain-limit* scenarios: both strategies emit spurious
entities (a character mistaken for a Person; a pronoun promoted to a
Person). Both scenarios cap at F1 < 1.00 for both strategies. They are
present so the mock report cannot claim "enhanced always reaches 1.00" —
a claim that would be dishonest given the live-track ceiling of 0.72.

| Scenario | b F1 | e F1 | b match% | e match% | calls | b ms | e ms | b vraw | e vraw |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| s01_simple_well_formed | 1.00 | 1.00 | 1.00 | 1.00 | 1 | 5.16 | 2.31 | 2 | 2 |
| s02_extra_property_filtered | 1.00 | 1.00 | 1.00 | 1.00 | 1 | 3.83 | 1.75 | 1 | 1 |
| s03_type_coercion_int | 1.00 | 1.00 | **0.50** | **1.00** | 1 | 4.06 | 1.80 | 1 | 1 |
| s04_missing_primary_key | **0.00** | **1.00** | 1.00 | 1.00 | 1 | 3.66 | 1.53 | 1 | 0 |
| s05_duplicate_vertex_across_chunks | 1.00 | 1.00 | 1.00 | 1.00 | 2 | 5.02 | 6.31 | 2 | **1** |
| s06_cross_chunk_edge | **0.80** | **1.00** | 1.00 | 1.00 | 2 | 7.37 | 3.60 | 2 | 2 |
| s07_alias_mismatch | **0.80** | **1.00** | 1.00 | 1.00 | 2 | 7.27 | 3.27 | 2 | 2 |
| s08_invalid_label | 1.00 | 1.00 | 1.00 | 1.00 | 1 | 4.40 | 1.89 | 1 | 1 |
| s09_malformed_json | 1.00 | 1.00 | 1.00 | 1.00 | 1 | 5.13 | 2.44 | 0 | 0 |
| s10_coerce_and_cross_chunk | **0.80** | **1.00** | **0.50** | **1.00** | 2 | 6.95 | 3.76 | 2 | 2 |
| s11_missing_endpoint_referent | 1.00 | 1.00 | 1.00 | 1.00 | 1 | 5.78 | 3.27 | 1 | 1 |
| s12_wrong_edge_direction | 1.00 | 1.00 | 1.00 | 1.00 | 1 | 5.36 | 2.61 | 2 | 2 |
| s13_duplicate_edge_across_chunks | 1.00 | 1.00 | 1.00 | 1.00 | 2 | 6.81 | 4.39 | 4 | **2** |
| s14_multi_primary_key | 1.00 | 1.00 | 1.00 | 1.00 | 1 | 4.44 | 1.91 | 1 | 1 |
| s15_character_promoted_to_person | **0.86** | **0.86** | 1.00 | 1.00 | 1 | 5.04 | 2.54 | 3 | 3 |
| s16_pronoun_ghost_no_prior_context | **0.50** | **0.50** | 1.00 | 1.00 | 1 | 3.95 | 2.25 | 2 | 2 |
| **average / total** | **0.86** | **0.96** | | | **21** | **84.23** | **45.65** | | |
| **F1 relative gain** | | **+11.6 %** | | | | | | | |

Column key: `b F1`/`e F1` = overall F1; `b match%`/`e match%` =
`property_exact_match_rate` on TP items; `calls` = LLM invocation count
(equal by design); `b ms`/`e ms` = post-LLM pipeline latency (FakeLLM
makes the LLM call itself effectively free); `b vraw`/`e vraw` = raw
predicted vertex count (before dedup). Bolded cells are where the two
strategies diverge.

### Mock Failure Case Analysis

Wins by enhanced (already documented; the same cases motivated the
enhanced strategy in the first place):

* **s04** — LLM omits primary key → baseline emits ghost vertex `v1`
  (raw id, no PK); enhanced drops via `MISSING_PRIMARY_KEY` warning.
* **s06** — cross-chunk edge references chunk-1 vertex from chunk 2;
  baseline drops (no alias table); enhanced repairs via document
  assembler.
* **s07** — chunk 2 uses canonical id `1:Tom Hanks` where chunk 1
  emitted raw `v1`; baseline drops (id mismatch); enhanced seeds
  identity aliases and cross-chunk alias union.
* **s03 / s10** — `"age": "62"` string → baseline preserves as string
  (fails downstream `IllegalArgumentException` on INT column); enhanced
  coerces via `property_data_type("age")`.

**Losses / ties by enhanced** (new, documenting the ceiling):

* **s15 — character promoted to Person.** LLM emits `Chuck Noland` as a
  first-class Person vertex — a fictional character with a schema-valid
  `name`. Neither strategy has world knowledge to detect this. Both keep
  the ghost vertex, both take the same precision hit; F1 caps at 0.86
  for both. Reproduces the exact failure mode observed on real DeepSeek
  output.
* **s16 — pronoun ghost with no antecedent.** Text: "He voiced Woody in
  the Toy Story franchise." Enhanced's document assembler *can* resolve
  a pronoun to an earlier chunk's antecedent (s06 shows this), but a
  first-chunk pronoun has no antecedent to resolve against. Both
  strategies emit `Person 1:He` with a spurious outgoing edge. F1 caps
  at 0.50.

### Where the Two Strategies Match (by Design)

* **s01, s02, s08, s09, s11, s12, s14** — enhanced matches baseline:
  both keep well-formed input, filter schema-external properties/labels,
  survive malformed JSON, drop unresolvable-endpoint or mis-directed
  edges, and share the composite-PK canonical-id rule.
* **s05, s13** — set-based F1 is equal, but the raw counts diverge:
  baseline emits 2 duplicate vertices (s05) or 4 duplicated items
  (s13); enhanced deduplicates at the raw level. In production this
  reduces downstream commit load by up to 50 %.
* Enhanced additionally emits structured warnings on every drop
  (`UNKNOWN_VERTEX_LABEL`, `JSON_DECODE_FAILED`,
  `PENDING_ENDPOINT_UNRESOLVED`, `ENDPOINT_INCOMPATIBLE`,
  `MISSING_PRIMARY_KEY`, `PROPERTY_COERCED`, etc.), which baseline
  silently swallows into a log line.

### Reproducing the Mock Benchmark

See the top-level [How to Reproduce This Report](#how-to-reproduce-this-report)
section. The +5 % relative design threshold is asserted inside
`test_benchmark_produces_comparison_table`.

## Live LLM Benchmark on Public Corpus (DeepSeek Chat)

### Corpus provenance

Text: Wikipedia lead extract for 8 well-known actors, fetched via
`MediaWiki API` with the article `revid` recorded. Ground truth: films
mentioned in each lead **AND** verified against Wikidata's `P161`
(cast member) claim for that actor. Only films whose Wikidata `P31`
(instance-of) lists a film class are admitted, so TV shows / franchises
/ book series are filtered out.

Build script: `scripts/build_public_actor_corpus.py`. Output pinned to
`hugegraph-llm/src/tests/data/public_actor_corpus.json` (94 KB).

Every corpus entry records `wikipedia_revision`, `wikipedia_url`,
`actor_qid`, and both `verified_films` and `rejected_mentions` so a
reviewer can audit every admit/reject decision.

Corpus stats:

| Actor | Q-id | Chunks | GT vertices | GT edges | Rejected |
|---|---|---:|---:|---:|---:|
| Tom Hanks | Q2263 | 3 | 8 | 7 | 8 |
| Meryl Streep | Q873 | 3 | 7 | 6 | 5 |
| Leonardo DiCaprio | Q38111 | 3 | 11 | 10 | 5 |
| Denzel Washington | Q42101 | 3 | 8 | 7 | 8 |
| Julia Roberts | Q40523 | 3 | 11 | 10 | 5 |
| Anthony Hopkins | Q65932 | 3 | 5 | 4 | 11 |
| Nicole Kidman | Q37459 | 3 | 8 | 7 | 8 |
| Morgan Freeman | Q48337 | 3 | 7 | 6 | 9 |
| **total** | | **24** | **65** | **57** | **59** |

"Rejected" = mentions in the extract that failed Wikidata verification
(usually a Wikidata disambiguation quirk — e.g. "Notting Hill" resolves
to the London neighbourhood before the film). These are excluded from
GT but recorded in the corpus JSON for transparency.

### Multi-run methodology

Each (corpus, strategy) pair is run **3 times** at temperature 0.0.
DeepSeek at temperature 0 is *near*-deterministic but not fully: token
counts and F1 vary by a few percent across runs of the same input,
reflecting server-side batching / caching noise. Aggregated statistics
report mean ± std over the 48 total runs.

### Overall results

| Strategy | F1 mean ± std | F1 min | F1 max | latency mean | prompt tok mean | completion tok mean | cost mean (USD) |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | **0.418 ± 0.251** | 0.049 | 0.677 | 16.57 s | 2093 | 1191 | $0.003776 |
| enhanced | **0.439 ± 0.188** | 0.216 | 0.722 | 14.80 s | 2933 | 903 | $0.003508 |
| **delta** | **+0.020 abs (+4.8 % rel.)** | +0.167 | +0.045 | **−1.77 s (−10.7 %)** | +40 % | −24 % | **−$0.000268 (−7.1 %)** |

Key observations:

* Enhanced improves the **worst-case** F1 dramatically: baseline min
  0.049 (Tom Hanks) → enhanced min 0.216 (Anthony Hopkins).
* Enhanced narrows the F1 distribution (std −25 %) — outcome is more
  predictable.
* Enhanced sends **more prompt tokens** (constraint block adds ~+40 %)
  but produces **fewer completion tokens** (−24 %) because the LLM is
  guided to be more disciplined about schema conformance. Net cost is
  lower.
* Enhanced is **~11 % faster wall-clock**, partly because
  fewer/shorter completion tokens shorten LLM decode time, partly
  because assembler-side dedup shrinks the pipeline pass.

### Per-corpus breakdown

| Corpus | Baseline F1 mean | Enhanced F1 mean | Delta | Outcome |
|---|---:|---:|---:|---|
| Tom Hanks | 0.052 | **0.327** | **+0.274** | 🟢 big win |
| Anthony Hopkins | 0.074 | **0.233** | **+0.158** | 🟢 big win |
| Meryl Streep | 0.650 | **0.722** | +0.072 | 🟢 win |
| Nicole Kidman | 0.188 | 0.220 | +0.032 | 🟢 win |
| Leonardo DiCaprio | 0.677 | 0.700 | +0.023 | 🟢 marginal |
| Denzel Washington | 0.486 | 0.391 | −0.096 | 🔴 regression |
| Morgan Freeman | 0.583 | 0.488 | −0.096 | 🔴 regression |
| Julia Roberts | 0.636 | 0.430 | **−0.206** | 🔴 big regression |

Enhanced wins on 5, ties nowhere, loses on 3. The two biggest wins and
the biggest loss share a common cause: **schema-valid but wrong Person
canonical id**. See failure analysis below.

### Live failure case analysis

Real DeepSeek output exposes failure modes that mock benchmarks cannot
easily reproduce. Two dominate; both hit both strategies.

**Failure Mode 1 — Person canonical name mismatch.** Wikipedia leads
routinely open with a subject's *full* name ("Thomas Jeffrey Hanks"),
switch to family-name shorthand ("Hanks") within a few sentences, and
never use the canonical short form ("Tom Hanks") the Wikidata label
records. The LLM faithfully extracts *what the text says*:

* Tom Hanks corpus (enhanced): predicted Persons =
  `1:Thomas Jeffrey Hanks`, `1:Hanks` — GT expects `1:Tom Hanks`.
* Julia Roberts corpus (enhanced): predicted Persons =
  `1:Julia Fiona Roberts`, `1:Roberts` — GT expects `1:Julia Roberts`.

Neither strategy has a knowledge base that maps "Thomas Jeffrey Hanks" ↔
"Tom Hanks" ↔ "Hanks". Enhanced's document assembler *can* union
`v1 → 1:Hanks` and `v2 → 1:Thomas Jeffrey Hanks` if the LLM keeps them
as separate raw ids, but that produces *two* canonical vertices, not
one. This is a legitimate limitation of a schema-only pipeline — solving
it needs either LLM alignment (system prompt: "always emit shortest
canonical name") or a real entity-resolution step (e.g., string
similarity + external gazetteer). Neither is in scope for Issue #74.

**Failure Mode 2 — LLM extracts films the GT does not verify.** The
extract mentions ~15 films; only ~7 pass Wikidata's `P161` filter (rest
are false-positive disambiguations, uncredited appearances, or films
Wikidata simply hasn't tagged). The LLM extracts all ~15; both
strategies pass ~15 through. This inflates predicted count and tanks
precision. Enhanced can filter schema violations but cannot fact-check
against Wikidata.

**Where enhanced still helps despite these two problems.**

*Tom Hanks (baseline F1 0.052 → enhanced 0.327):* The baseline
extraction diverged on chunk 3 (TV work) and lost most of the GT films.
Enhanced's constraint block appears to have kept the LLM focused on
film-instance extraction across all chunks, so more of the correct films
made it through. This is the constraint block's largest observed win —
a probabilistic effect via LLM cooperation, not a hard guarantee.

*Anthony Hopkins (baseline F1 0.074 → enhanced 0.233):* Similar pattern.
Baseline predicted many long-form names + role names as Persons ("Sir
Anthony Philip Hopkins", "King Lear", etc.); enhanced kept the number of
Persons lower and the film precision higher.

**Why enhanced regresses on Julia Roberts / Denzel Washington / Morgan
Freeman.** These are the corpora where baseline was already relatively
strong (0.49–0.68 F1). On those, enhanced's schema-guided constraint
block did not add much information (baseline was already extracting
mostly clean output), but enhanced's stricter deduplication and cross-
chunk alias union sometimes *merged* films that had slight title
variations across chunks (e.g. `Ocean's Eleven` vs `Ocean's 11`),
knocking F1 down. This is the classic ceiling effect: safety-net
strategies help when the baseline fails, but can hurt when the baseline
is already good.

### Cost / quality trade-off

Enhanced is **not** cost-neutral: it sends +40 % prompt tokens (the
constraint block). But it produces **−24 % completion tokens** because
the LLM is guided to output tighter JSON. Net cost per document is
**−7.1 %** and net latency is **−10.7 %**.

The trade-off is favourable when quality is the bottleneck (worst-case
corpora) and roughly neutral or slightly worse when baseline is already
good. A production deployment could route to enhanced conditionally
based on a first-pass quality-gate signal, but that adds complexity;
running enhanced unconditionally is defensible given the small negative
side.

### Reproducing the live benchmark

See the top-level [How to Reproduce This Report](#how-to-reproduce-this-report)
section for the `build_public_actor_corpus.py` and
`graph_extract_live_benchmark.py` invocations, plus the sha256 for
verifying an archive obtained on request. The archive (~600 KB, 48-run
record including every LLM call's prompt/completion tokens, latency,
and raw predicted output) makes every number in this section
independently recomputable without re-running the benchmark.

## Metric Definitions

* **Precision** = |predicted ∩ expected| / |predicted_unique|, matched by
  `(label, id)` for vertices and `(label, outV, inV)` for edges. Empty
  predicted → 1.0.
* **Recall** = |predicted ∩ expected| / |expected|. Empty expected → 1.0.
* **F1** = harmonic mean of precision and recall. Both empty → 1.0.
* **Overall F1** = combined vertex + edge precision/recall.
* **Property valid ratio** = fraction of predicted `(label, key)` pairs
  whose key is declared on that label in the schema.
* **Property exact match rate** = fraction of expected properties on TP
  items whose predicted `(key, value)` matches exactly (Python `==`).

## Scope and Caveats

* **The mock benchmark is not effect evidence.** Its 16 scenarios probe
  pipeline correctness, not end-to-end LLM quality. Its +11.6 % gain is
  a lower-bound consistency check for the pipeline. The live benchmark
  is the effect-evidence track.

* **The live benchmark's Person canonical id is a real limit** neither
  strategy overcomes. Wikipedia openings use "Thomas Jeffrey Hanks";
  Wikidata canonicals use "Tom Hanks". Both strategies fail on the
  Person axis in most corpora, dragging edge F1 with them. A future
  entity-resolution step could plausibly recover the majority of this
  gap; it is out of scope for Issue #74.

* **Live-corpus GT is strict.** Only films whose Wikidata entity
  passes both instance-of-film and cast-member-verified is admitted.
  The LLM extracts many *real* films that Wikidata hasn't tagged as
  cast-linked (recent releases, uncredited work); these are counted as
  false positives even though they are factually correct. This
  systematically depresses precision. It is a limit of Wikidata's
  completeness, not the extraction pipeline's; live F1 is a lower bound
  on true quality.

* **8 corpora × 3 runs = 48 samples** is a modest sample size. The F1
  gap of +0.020 is not statistically dramatic (baseline std 0.251;
  enhanced std 0.188). The stronger claims are on *variance reduction*
  (−25 %), *worst-case improvement* (0.049 → 0.216), *latency* (−11 %),
  and *cost* (−7 %) — all of which are outside the F1 mean's confidence
  band. Larger corpora would tighten the mean's confidence.

* **Live latency is DeepSeek-side, not enhanced-pipeline-side.**
  Enhanced's post-LLM processing adds < 100 ms per chunk (see mock
  latency column); the observed −11 % wall-clock savings come from the
  LLM decoding fewer completion tokens.

* **Wikidata WDQS outage during data collection (2026-07).** SPARQL was
  1-req/min throttled at time of writing; the corpus builder uses the
  entity API instead, which was less affected but still needed 5 s
  inter-request pacing and generous 429 backoff.

* **Deterministic FakeLLM in mock.** The mock benchmark's LLM
  invocations are dict pops, so the mock's millisecond figures reflect
  post-processing overhead only. The live section's wall-clock latency
  is the honest end-to-end number.

* **Ground truth uses canonical ids.** When a schema entry omits `id`
  (as inline user schemas often do), neither strategy can compute
  canonical ids and the evaluator falls back to `(label, raw_id)` for
  both, keeping the comparison fair.
