# Text2Gremlin Corpus Generalization

[English](README.md) | [中文](./README_zh.md)

Generate a large and diverse set of Gremlin queries and their corresponding natural language descriptions based on ASTs and templates, and perform multi-stage data augmentation and preference data synthesis using LLMs for training and evaluating text-to-Gremlin models.

The synthesized dataset is published on Hugging Face: [Lriver/Text2Gremlin](https://huggingface.co/datasets/Lriver/Text2Gremlin). Use it directly if you only need the generated data; run the local pipeline when you need to regenerate, customize, or audit the intermediate artifacts.

## Dataset

Pre-generated Text2Gremlin data is available at:

```text
https://huggingface.co/datasets/Lriver/Text2Gremlin
```

The repository pipeline generates the same classes of artifacts locally under `output/`, including AST-generalized corpora, multi-style LLM translations, scenario migration results, merged text-to-Gremlin pairs, syntax analysis reports, and DPO preference data. `output/` is gitignored because these files can be large and can be regenerated or downloaded from Hugging Face.

## Quick Start

### 1. Environment Setup
Python version: 3.12.10
```bash
pip install -r requirements.txt
```

### 2. Configuration
Copy the example config and fill in your settings:
```bash
cp config_example.json config.json
```

Edit `config.json` with your LLM API configuration:
```json
"llm": {
    "base_url": "http://your-llm-server:port/v1",
    "api_key": "your-api-key",
    "model": "your-model-name",
    "temperature": 1.0,
    "max_retries": 3,
    "max_concurrency": 5,
    "save_interval": 50,
    "timeout": 40
},
"migration": {
    "migration_mode": "same_operation",
    "same_operation_sample_count": 3
}
```

> ⚠️ `config.json` contains sensitive information and is excluded via `.gitignore`. Do not commit it.

### 3. Running

#### Stage 1: AST Generalization
```bash
python generate_corpus.py
```

#### Stages 2–5: LLM Augmentation Pipeline
```bash
# Run all LLM augmentation stages (translate → migrate → merge → DPO)
python run_llm_pipeline.py

# Start from a specific stage
python run_llm_pipeline.py --stage migrate

# Run a single stage
python run_llm_pipeline.py --stage merge --stop merge
```

Each stage can also be run independently:
```bash
# Multi-style translation
python -m llm_augment.generalize_llm

# Scenario migration
python -m llm_augment.migrate_scenario

# Optional: generate mixed CRUD samples during scenario migration
python -m llm_augment.migrate_scenario --migration-mode mixed_operations

# Dataset merging
python -m llm_augment.merge_dataset

# DPO preference data generation
python -m llm_augment.generate_dpo_data
```

#### Syntax Analysis
```bash
python analyze_syntax.py
```

---

## Data Generation Pipeline

```text
Stage 1: AST Generalization    generate_corpus.py
          251 templates → ~1500 entries (query + simple description)
               ↓
Stage 2: LLM Multi-style       llm_augment/generalize_llm.py
          Translation
          ×6 styles → ~9000 entries (4 fixed + 2 random tones)
               ↓
Stage 3: Scenario Migration     llm_augment/migrate_scenario.py
          ×20 domains → same-operation samples by default, optional mixed CRUD, syntax-checked
               ↓
Stage 4: Dataset Merging        llm_augment/merge_dataset.py
          Merge translations + migrations → text2gremlin_dataset_*.json for training/evaluation analysis
               ↓
Stage 5: DPO Preference Data    llm_augment/generate_dpo_data.py
          Uses text2gremlin_pairs_*.json + migrated_*.json as inputs
          Type A (multi-task) + Type B (single-task) + Type C (long-chain)
          → ~8900 preference pairs (21 domains)
               ↓
Published Dataset               Hugging Face: Lriver/Text2Gremlin
```

---

## Project Structure

```text
├── generate_corpus.py          # AST generalization entry point
├── run_llm_pipeline.py         # Unified LLM pipeline runner
├── analyze_syntax.py           # Gremlin syntax distribution analysis
├── gremlin_templates.csv       # Query templates (251 entries)
├── config.json                 # Configuration (gitignored)
├── config_example.json         # Configuration example
├── requirements.txt            # Python dependencies
│
├── llm_augment/                # LLM augmentation package
│   ├── __init__.py
│   ├── generalize_llm.py       # Stage 2: Multi-style translation
│   ├── migrate_scenario.py     # Stage 3: Scenario migration
│   ├── merge_dataset.py        # Stage 4: Dataset merging
│   └── generate_dpo_data.py    # Stage 5: DPO preference data
│
├── base/                       # AST generalization core engine
│   ├── generator.py            # Generalization controller + syntax checker
│   ├── Config.py               # Configuration management
│   ├── Schema.py               # Schema and data management
│   ├── GremlinParse.py         # Data structure definitions
│   ├── GremlinExpr.py          # Complex expressions (predicates, anonymous traversals)
│   ├── GremlinTransVisitor.py  # AST parsing
│   ├── TraversalGenerator.py   # Traversal generator
│   ├── GremlinBase.py          # Translation engine
│   ├── gremlin/                # ANTLR-generated Gremlin parser
│   └── template/               # Translation dictionaries
│
├── db_data/                    # Data and schemas
│   ├── schema/                 # Graph database schemas
│   └── reference/              # Multi-domain schemas for migration
│
└── output/                     # Output directory
    ├── generated_corpus_*.json
    ├── llm_translated_*.json
    ├── text2gremlin_pairs_*.json
    ├── migrated_*.json
    ├── text2gremlin_dataset_*.json
    └── preference_data/        # DPO preference data
```

### ANTLR Generated Gremlin Parser Files

Files under `base/gremlin/` are generated from `base/gremlin/Gremlin.g4` and committed to the repository, so the pipeline can run without requiring every user to install ANTLR locally. The committed generated files include `GremlinLexer.py`, `GremlinParser.py`, `GremlinListener.py`, `GremlinVisitor.py`, and the corresponding `.interp` and `.tokens` artifacts.

To regenerate the parser with ANTLR 4.13.1, run:

```bash
cd text2gremlin/AST_Text2Gremlin/base/gremlin
java -jar /path/to/antlr-4.13.1-complete.jar -Dlanguage=Python3 -visitor Gremlin.g4
```

After regenerating, run the end-to-end quality test:

```bash
uv run pytest text2gremlin/AST_Text2Gremlin/tests/test_generation_e2e_quality.py -q
```

---

## Configuration

### LLM Configuration (`config.json` → `llm`)

| Field | Description | Default |
|-------|-------------|---------|
| base_url | LLM API endpoint | Required |
| api_key | API key | Required |
| model | Model name | Required |
| temperature | Sampling temperature | 1.0 |
| max_retries | Max retries per item | 3 |
| max_concurrency | Concurrent requests | 5 |
| save_interval | Incremental save interval | 50 |
| timeout | Request timeout (seconds) | 40 |

### Scenario Migration Configuration (`config.json` → `migration`)

| Field | Description | Default |
|-------|-------------|---------|
| migration_mode | `same_operation` generates samples with the same operation type as the source query. `mixed_operations` keeps the legacy mixed CRUD prompt. | `same_operation` |
| same_operation_sample_count | Number of samples requested per migration task in `same_operation` mode. The model may return fewer if the source pattern does not fit the target schema. | 3 |

CLI arguments override `config.json` for one run:

```bash
python -m llm_augment.migrate_scenario --migration-mode same_operation --same-operation-sample-count 5
python -m llm_augment.migrate_scenario --migration-mode mixed_operations
```

### Template File (`gremlin_templates.csv`)

| Column | Description | Example |
|--------|-------------|---------|
| template | Gremlin query template | `g.V().hasLabel('person')` |
| description | Template description (optional) | Query all persons |

### Combination Control (`base/combination_control_config.json`)

Controls query generation volume during AST generalization:
- Chain length categories: short (≤4 steps), medium (5–6), long (7–8), extra-long (≥9)
- Data value filling: 1 value for intermediate steps, 2–3 for terminal steps
- Property generalization: dynamically adjusted based on chain length

---

## Output Formats

Published generated data can be downloaded from [Lriver/Text2Gremlin](https://huggingface.co/datasets/Lriver/Text2Gremlin). The formats below describe the local pipeline artifacts that lead to the published dataset.

### AST Generalization (`generated_corpus_*.json`)
```json
{
  "metadata": { "total_unique_queries": 1564, "..." : "..." },
  "corpus": [
    {
      "query": "g.V().hasLabel('person')",
      "description": "Start from the graph and query person vertices",
      "metadata": {
        "sample_kind": "prefix",
        "recipe_step_count": 3,
        "emitted_step_count": 2,
        "top_level_step_count": 2,
        "has_nested_traversal": false
      }
    }
  ]
}
```

#### Generated Sample Metadata

Stage 1 preserves Gremlin's procedural traversal structure during AST generalization. The generator emits prefix queries by default because many Gremlin prefixes are valid standalone traversals and help the corpus cover intermediate query shapes. Each corpus item still keeps the legacy `query` and `description` fields, and newer output also includes `metadata`:

```json
{
  "query": "g.V().hasLabel('person')",
  "description": "Start from the graph and query person vertices",
  "metadata": {
    "sample_kind": "prefix",
    "recipe_step_count": 3,
    "emitted_step_count": 2,
    "top_level_step_count": 2,
    "has_nested_traversal": false
  }
}
```

`sample_kind` has three main values:

- `prefix`: an intermediate traversal prefix emitted during recursive generation.
- `complete`: a query that covers every step in the original recipe.
- `enhancement`: a query produced by appending random enhancement steps to a prefix or complete query.

The generator completes recursive generalization first, then applies a stable post-generation stratified selection policy when `max_total_combinations` is configured. In other words, the final output limit only decides which samples are retained; it does not stop recursive generalization early. The selection policy prioritizes complete queries and representative prefix queries, then fills the remaining slots with a stable ordering.

### LLM Translation (`llm_translated_*.json`)
```json
{
  "corpus": [
    {
      "query": "g.V().hasLabel('person')",
      "metadata": {
        "sample_kind": "complete",
        "recipe_step_count": 2,
        "emitted_step_count": 2,
        "top_level_step_count": 2,
        "has_nested_traversal": false
      },
      "translations": [
        { "style": "zh_formal", "text": "查询所有人类型的顶点" },
        { "style": "en_casual", "text": "Find all person nodes" }
      ]
    }
  ]
}
```

### Text2Gremlin Pairs (`text2gremlin_pairs_*.json`)
Generated by the scenario migration stage from `llm_translated_*.json`. It picks one fixed translation style per query for movie-domain DPO input.

```json
{
  "metadata": {
    "source_file": "output/llm_translated_20260531_120000.json",
    "total_pairs": 1564,
    "style_distribution": { "zh_formal": 392, "en_casual": 391 }
  },
  "pairs": [
    {
      "text": "Query all persons",
      "gremlin": "g.V().hasLabel('person')",
      "style": "en_formal",
      "source_metadata": {
        "sample_kind": "complete",
        "recipe_step_count": 2,
        "emitted_step_count": 2,
        "top_level_step_count": 2,
        "has_nested_traversal": false
      }
    }
  ]
}
```

### Scenario Migration (`migrated_*.json`)
```json
{
  "migrations": [
    {
      "target_domain": "ecommerce",
      "source_metadata": {
        "sample_kind": "complete",
        "recipe_step_count": 2,
        "emitted_step_count": 2,
        "top_level_step_count": 2,
        "has_nested_traversal": false
      },
      "generated_samples": [
        { "operation": "read", "query": "g.V()...", "natural_language": "..." }
      ]
    }
  ]
}
```

### Merged Text2Gremlin Dataset (`text2gremlin_dataset_*.json`)
Generated by `merge_dataset.py` from the latest or explicitly supplied `llm_translated_*.json` and `migrated_*.json`. This file is compatible with `analyze_syntax.py`.

```json
{
  "metadata": {
    "total": 3,
    "sources": {
      "llm_translated": { "file": "output/llm_translated_20260531_120000.json", "count": 1 },
      "migrated": { "file": "output/migrated_20260531_130000.json", "count": 2 }
    },
    "crud_distribution": { "read": 2, "create": 1 }
  },
  "corpus": [
    {
      "query": "g.V().hasLabel('person')",
      "text": "Query all persons",
      "domain": "movie",
      "operation": "read",
      "language_style": "en_formal",
      "source": "llm_translated",
      "source_metadata": {
        "sample_kind": "complete",
        "recipe_step_count": 2,
        "emitted_step_count": 2,
        "top_level_step_count": 2,
        "has_nested_traversal": false
      }
    }
  ]
}
```

### DPO Preference Data (`preference_data/dpo_data_*.json`)
```json
{
  "metadata": {
    "total_samples": 8920,
    "rejected_count": 3032,
    "type_distribution": { "A": 4380, "B": 2318, "C": 2222 },
    "domain_distribution": { "movie": 401, "ecommerce": 399, "..." : "..." },

  },
  "samples": [
    {
      "task_id": "pref_MOVI_A_0001",
      "task_type": "A",
      "domain": "movie",
      "source_queries": [
        { "text": "Query all actors", "gremlin": "g.V().hasLabel('person')" }
      ],
      "input": { "instruction": "Please query all actors and update..." },
      "chosen": { "style": "groovy", "code": "def actors = g.V()..." },
      "rejected": { "style": "gremlin", "code": "g.V().hasLabel..." },
      "preference_reason": ["Groovy style is clearer...", "..."]
    }
  ]
}
```

---

## Key Features

### AST Generalization
Generates multiple variants from a single template with intelligent combinatorial control and automatic deduplication:
```text
Template: g.V().hasLabel('person').out('acted_in')
  → g.V().hasLabel('movie').out('acted_in')
  → g.V().hasLabel('person').out('directed')
  → ...
```

### LLM Multi-style Translation
Each query is translated into 6 styles (4 fixed + 2 random):
- Chinese formal / Chinese casual / English formal / English casual
- Mixed Chinese-English / Abbreviated / Q&A style / With typos

### Scenario Migration
Migrates movie-domain data to 20 business domains. By default, each migrated sample keeps the same operation type as the source query and asks for 3 samples per target scenario. The legacy mixed CRUD mode can still be enabled with `--migration-mode mixed_operations`. Every generated Gremlin query is validated via ANTLR syntax checking.

During this stage, `text2gremlin_pairs_*.json` is also prepared from the translation output for movie-domain DPO generation.

### DPO Preference Data
Three task types generate Groovy vs Gremlin preference pairs across 21 domains (movie + 20 migrated), totaling 8920 samples:

- **Type A (Multi-task Composition, 4380 samples)**: Combines 2–5 simple queries into a composite task
  - chosen: Groovy imperative style (def variables, .next(), return map)
  - rejected: Pure Gremlin functional style (as/select/project forced into a single chain)
  - Automatically detects command conflicts (e.g., delete before update), reorders or rejects
- **Type B (Single Task, 2318 samples)**: Simple queries that don't need Groovy wrapping
  - chosen: Original pure Gremlin
  - rejected: Over-engineered Groovy wrapper
- **Type C (Long-chain Decomposition, 2222 samples)**: Complex long-chain queries decomposed into steps
  - chosen: Groovy multi-step style
  - rejected: Original long-chain Gremlin

### Pipeline Features
- Concurrency control: `asyncio.wait(FIRST_COMPLETED)` + Semaphore + batched task creation
- Incremental saving: auto-saves every 50 items, supports resumption
- Pydantic validation: strict format validation for all LLM outputs
- ANTLR syntax checking: pure Gremlin code is syntax-validated (Groovy code is skipped due to variable reference incompatibility with ANTLR)
- Per-item retry: failed items retry with exponential backoff without affecting others
- No-comment policy: all generated Groovy/Gremlin code is comment-free

### Published Dataset
The final synthesized data has been uploaded to [Hugging Face datasets: Lriver/Text2Gremlin](https://huggingface.co/datasets/Lriver/Text2Gremlin). Prefer the Hugging Face dataset for downstream training/evaluation consumption, and use this repository when you need to reproduce or modify the generation pipeline.
