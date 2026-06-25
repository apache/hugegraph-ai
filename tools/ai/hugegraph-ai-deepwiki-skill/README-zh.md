# HugeGraph AI 仓库知识助手

[English](README.md) | [中文](README-zh.md)

这个独立模块将 [Apache HugeGraph AI](https://github.com/apache/hugegraph-ai) 源码仓库问答能力打包为 Claude Code 和 Codex 可安装的 skill。

DeepWiki 是底层线上知识库和 MCP 传输通道：

```text
https://deepwiki.com/apache/hugegraph-ai
https://mcp.deepwiki.com/mcp
```

## 功能

- 回答 HugeGraph AI 模块、agent、RAG 工作流、图增强 AI、模型集成、配置、示例、安装和实现细节相关问题。
- 使用 `read_wiki_contents` 构建本地 DeepWiki wiki 缓存，并优先搜索缓存。
- 当缓存内容不能直接、精准回答问题时，使用 `ask_question` 获取线上答案。
- 普通问答不会 clone 上游源码仓库。

## 前置要求

- Python 3.10 或更高版本，用于运行随附的 MCP 客户端脚本。
- 当前环境需要能访问 `https://mcp.deepwiki.com/mcp`。

## 目录结构

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

## Claude Code 安装

从当前仓库安装：

```bash
cd tools/ai/hugegraph-ai-deepwiki-skill
claude plugin marketplace add "$(pwd)"
claude plugin install hugegraph-ai-deepwiki-skill@hugegraph-ai-deepwiki-skill
```

从已发布分支安装时，先 clone 仓库，再从本地模块路径安装：

```bash
git clone -b <branch> https://github.com/<owner>/hugegraph-ai.git
cd hugegraph-ai/tools/ai/hugegraph-ai-deepwiki-skill
claude plugin marketplace add "$(pwd)"
claude plugin install hugegraph-ai-deepwiki-skill@hugegraph-ai-deepwiki-skill
```

手动安装用户级 skill：

```bash
mkdir -p ~/.claude/skills
cp -R plugins/hugegraph-ai-deepwiki-skill/skills/hugegraph-ai-deepwiki-skill ~/.claude/skills/
```

### 让 Claude Code 自动安装

在 HugeGraph AI 仓库根目录的 Claude Code 里粘贴：

```text
请从当前 checkout 安装 HugeGraph AI 仓库知识助手。进入 `tools/ai/hugegraph-ai-deepwiki-skill`，运行 `claude plugin marketplace add "$(pwd)"`，然后运行 `claude plugin install hugegraph-ai-deepwiki-skill@hugegraph-ai-deepwiki-skill`。不要硬编码绝对路径。
```

## Codex 安装

从当前仓库安装：

```bash
cd tools/ai/hugegraph-ai-deepwiki-skill
codex plugin marketplace add "$(pwd)"
codex plugin add hugegraph-ai-deepwiki-skill@hugegraph-ai-deepwiki-skill
```

从已发布分支安装时，先 clone 仓库，再从本地模块路径安装：

```bash
git clone -b <branch> https://github.com/<owner>/hugegraph-ai.git
cd hugegraph-ai/tools/ai/hugegraph-ai-deepwiki-skill
codex plugin marketplace add "$(pwd)"
codex plugin add hugegraph-ai-deepwiki-skill@hugegraph-ai-deepwiki-skill
```

如果当前 Codex 版本不能直接安装 plugin，可以安装 raw skill：

```bash
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$CODEX_HOME/skills"
cp -R plugins/hugegraph-ai-deepwiki-skill/skills/hugegraph-ai-deepwiki-skill "$CODEX_HOME/skills/"
```

### 让 Codex 自动安装

在 HugeGraph AI 仓库根目录的 Codex 里粘贴：

```text
请从当前 checkout 安装 HugeGraph AI 仓库知识助手。进入 `tools/ai/hugegraph-ai-deepwiki-skill`，运行 `codex plugin marketplace add "$(pwd)"`，然后运行 `codex plugin add hugegraph-ai-deepwiki-skill@hugegraph-ai-deepwiki-skill`。如果当前 Codex 构建没有 plugin add 命令，就把 `plugins/hugegraph-ai-deepwiki-skill/skills/hugegraph-ai-deepwiki-skill` 复制到 `${CODEX_HOME:-$HOME/.codex}/skills`。不要硬编码绝对路径。
```

## 使用方式

安装后，可以在提问时显式指定：

```text
使用 $hugegraph-ai-deepwiki-skill 解释 HugeGraph AI 的 RAG 工作流。
```

Apache HugeGraph 图数据库相关问题请安装 `apache/hugegraph` 仓库中的独立 HugeGraph 仓库知识助手。
