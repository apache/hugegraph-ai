---
name: hugegraph-ai-deepwiki-skill
description: Use this skill as a repository knowledge assistant for Apache HugeGraph AI, apache/hugegraph-ai source code, architecture, modules, examples, agents, RAG workflows, graph-enhanced AI features, model integration, configuration, installation, demos, or implementation details. It answers questions grounded in apache/hugegraph-ai and uses the official DeepWiki MCP wiki as the underlying retrieval channel.
metadata:
  short-description: Apache HugeGraph AI repository assistant
---

# HugeGraph AI Repository Knowledge Assistant

Answer questions about the Apache HugeGraph AI source repository. Use the official DeepWiki MCP server as the underlying knowledge retrieval channel.

- Source repository: `https://github.com/apache/hugegraph-ai`
- DeepWiki page: `https://deepwiki.com/apache/hugegraph-ai`
- MCP endpoint: `https://mcp.deepwiki.com/mcp`
- Default repository: `apache/hugegraph-ai`
- Runtime requirements: Python 3.10+ and network access to the MCP endpoint.

## Default Workflow

1. Preserve the user's question, including code snippets, version constraints, error messages, model/provider details, and environment details.
2. Change directory to this skill directory, the directory containing this `SKILL.md`.
3. Search the local DeepWiki wiki cache for relevant context. If the cache does not exist yet, this command fetches `read_wiki_contents` from DeepWiki once and saves it under the user's cache directory. It prints only relevant snippets, not the full wiki dump:

```bash
python3 scripts/deepwiki_mcp.py context --repo hugegraph-ai --query "<user question>"
```

4. Answer from cached context only when the snippets directly and precisely answer the user's question. If they are merely related background, continue to `ask`.
5. For broad navigation questions, read the wiki structure instead:

```bash
python3 scripts/deepwiki_mcp.py structure --repo hugegraph-ai
```

6. If the cached wiki context does not directly and precisely answer the question, do not answer the user yet. You must use DeepWiki's AI `ask_question` tool to request an online answer:

```bash
python3 scripts/deepwiki_mcp.py ask --repo hugegraph-ai --question "<user question>"
```

7. For `ask`, preserve the user's original question. Do not expand it with extra requirements, long source-reference requests, or your own multi-part prompt; longer generated questions are more likely to time out.
8. If `ask` returns uncertainty, times out, or reports a transport/query error, retry once with the shortest faithful form of the user's original question. If it still fails, say so plainly and answer only from the cached context if it is sufficient.
9. If the user needs source references for an `ask` answer, use the cached context or contents to identify the relevant wiki page snippets and source-file references. `ask` usually returns the final answer plus suggested wiki pages or a DeepWiki search link, not the raw code files used to generate the answer.

## Routing Rules

- Use `structure` first for navigation, table-of-contents, onboarding, or "where should I start?" questions.
- Use `context` first for normal Q&A, source-reference requests, and token-efficient grounding.
- Use `ask` after `context` whenever cached snippets do not provide a direct and precise answer, or when the question needs synthesis across multiple areas. Do not answer directly from related-but-insufficient cached snippets.
- If both an online answer and source references are needed, run `ask` for the answer and use `context` to collect source references.
- Do not clone the repository for ordinary Q&A or verification. If current source verification is truly required, prefer online source links or raw GitHub files and clearly distinguish that from DeepWiki-grounded content.

## When to Read Structure or Contents

For broad orientation questions, onboarding questions, or "where should I start?" prompts, inspect the wiki structure:

```bash
cd <directory-containing-this-SKILL.md>
python3 scripts/deepwiki_mcp.py structure --repo hugegraph-ai
```

If the user needs a fuller wiki dump for offline review or synthesis, read the wiki contents:

```bash
cd <directory-containing-this-SKILL.md>
python3 scripts/deepwiki_mcp.py contents --repo hugegraph-ai
```

The `contents` command uses the same local cache by default. Use `--refresh` only when the user explicitly needs a fresh DeepWiki snapshot.

For normal Q&A, prefer `context` over `contents` so only the relevant cached snippets enter the model context. When the cached wiki context does not directly and precisely answer the question, run `ask` for an online DeepWiki answer before responding.

## Repository Profile

The repository alias lives in `references/repos.json`.

- `hugegraph-ai` maps to `apache/hugegraph-ai`.
- For Apache HugeGraph core graph database questions, use the separate `hugegraph-deepwiki-skill` instead of this skill.

## Answering Guidance

- Optimize answers for newcomers: explain the relevant concept, name the module or example to inspect next, and give a short next step when DeepWiki provides one.
- Keep responses practical: include class/module names, configuration keys, scripts, commands, or example paths when DeepWiki provides them.
- Prefer online DeepWiki retrieval and cached wiki search. Do not clone the source repository just to answer a question.
- If the user asks for code changes in a local HugeGraph AI checkout, use DeepWiki for orientation, then inspect and edit the local repository directly.
- Do not invent details that DeepWiki does not provide. Clearly distinguish DeepWiki-grounded facts from your own inference.
- For version-sensitive release, dependency, provider, or API-compatibility questions, verify with the live repository or official docs when the user needs current facts beyond the DeepWiki answer.
