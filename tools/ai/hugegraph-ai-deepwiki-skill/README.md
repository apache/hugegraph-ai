# HugeGraph AI Repository Assistant

[中文](README-zh.md) | [English](README.md)

This standalone module packages a Claude Code and Codex skill for answering questions about the [Apache HugeGraph AI](https://github.com/apache/hugegraph-ai) source repository.

DeepWiki is used as the online knowledge and MCP transport layer:

```text
https://deepwiki.com/apache/hugegraph-ai
https://mcp.deepwiki.com/mcp
```

## What It Does

- Answers repository-grounded questions about HugeGraph AI modules, agents, RAG workflows, graph-enhanced AI features, model integration, configuration, examples, installation, and implementation details.
- Uses `read_wiki_contents` to build a local DeepWiki wiki cache and searches that cache before answering.
- Uses `ask_question` when the cached context does not directly and precisely answer the question.
- Avoids cloning upstream repositories for ordinary Q&A.

## Requirements

- Python 3.10 or later for the bundled MCP client script.
- Network access to `https://mcp.deepwiki.com/mcp`.

## Layout

```text
tools/ai/hugegraph-ai-deepwiki-skill/
├── README.md
├── README-zh.md
├── .agents/plugins/marketplace.json
├── .claude-plugin/marketplace.json
└── plugins/hugegraph-ai-deepwiki-skill/
    ├── .claude-plugin/plugin.json
    ├── .codex-plugin/plugin.json
    └── skills/hugegraph-ai-deepwiki-skill/
        ├── SKILL.md
        ├── agents/openai.yaml
        ├── references/repos.json
        └── scripts/deepwiki_mcp.py
```

## Claude Code Install

From this repository:

```bash
cd tools/ai/hugegraph-ai-deepwiki-skill
claude plugin marketplace add "$(pwd)"
claude plugin install hugegraph-ai-deepwiki-skill@hugegraph-ai-deepwiki-skill
```

From a published branch, clone the repository first and install from the local module path:

```bash
git clone -b <branch> https://github.com/<owner>/hugegraph-ai.git
cd hugegraph-ai/tools/ai/hugegraph-ai-deepwiki-skill
claude plugin marketplace add "$(pwd)"
claude plugin install hugegraph-ai-deepwiki-skill@hugegraph-ai-deepwiki-skill
```

Manual user-level skill install:

```bash
mkdir -p ~/.claude/skills
cp -R plugins/hugegraph-ai-deepwiki-skill/skills/hugegraph-ai-deepwiki-skill ~/.claude/skills/
```

### Ask Claude Code To Install It

Paste this into Claude Code from the HugeGraph AI repository root:

```text
Install the HugeGraph AI repository assistant from this checkout. Enter `tools/ai/hugegraph-ai-deepwiki-skill`, run `claude plugin marketplace add "$(pwd)"`, then run `claude plugin install hugegraph-ai-deepwiki-skill@hugegraph-ai-deepwiki-skill`. Do not hardcode absolute paths.
```

## Codex Install

From this repository:

```bash
cd tools/ai/hugegraph-ai-deepwiki-skill
codex plugin marketplace add "$(pwd)"
codex plugin add hugegraph-ai-deepwiki-skill@hugegraph-ai-deepwiki-skill
```

From a published branch, clone the repository first and install from the local module path:

```bash
git clone -b <branch> https://github.com/<owner>/hugegraph-ai.git
cd hugegraph-ai/tools/ai/hugegraph-ai-deepwiki-skill
codex plugin marketplace add "$(pwd)"
codex plugin add hugegraph-ai-deepwiki-skill@hugegraph-ai-deepwiki-skill
```

If your Codex build cannot install plugins directly, install the raw skill:

```bash
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$CODEX_HOME/skills"
cp -R plugins/hugegraph-ai-deepwiki-skill/skills/hugegraph-ai-deepwiki-skill "$CODEX_HOME/skills/"
```

### Ask Codex To Install It

Paste this into Codex from the HugeGraph AI repository root:

```text
Install the HugeGraph AI repository assistant from this checkout. Enter `tools/ai/hugegraph-ai-deepwiki-skill`, run `codex plugin marketplace add "$(pwd)"`, then run `codex plugin add hugegraph-ai-deepwiki-skill@hugegraph-ai-deepwiki-skill`. If this Codex build has no plugin add command, copy `plugins/hugegraph-ai-deepwiki-skill/skills/hugegraph-ai-deepwiki-skill` into `${CODEX_HOME:-$HOME/.codex}/skills`. Do not hardcode absolute paths.
```

## Usage

After installation, ask for the skill explicitly when needed:

```text
Use $hugegraph-ai-deepwiki-skill to explain the HugeGraph AI RAG workflow.
```

For Apache HugeGraph graph database questions, install the separate HugeGraph repository assistant from the `apache/hugegraph` repository instead.
