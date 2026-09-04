# HugeGraph MCP

[English](README.md)

HugeGraph MCP 是 HugeGraph Server 的安全、可控 Model Context Protocol 适配层。它提供稳定的结构化工具，统一执行配置和权限检查，并持久化不可变写入计划与执行结果。

**要求 HugeGraph Server >= 1.7.0。** 默认图路径是 `DEFAULT/hugegraph`，依赖旧版本不具备的 graphspace 路由 API。

## 快速开始

安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后以只读模式启动：

```bash
export HUGEGRAPH_URL=http://hugegraph.example.com:8080
export HUGEGRAPH_GRAPH_PATH=DEFAULT/hugegraph
export HUGEGRAPH_USER=admin
export HUGEGRAPH_PASSWORD=admin
export HUGEGRAPH_MCP_READONLY=true

uvx --from hugegraph-mcp==1.7.0 hugegraph-mcp
```

进程通过 stdout 提供 MCP JSON-RPC。除非明确需要受控写入，请保持 `HUGEGRAPH_MCP_READONLY=true`。默认工具集为 `v2_core`；只有旧客户端需要 10 工具契约时才在启动前设置 `HUGEGRAPH_MCP_TOOLSET=v1`。

支持 JSON Server 配置的 MCP 客户端可使用：

```json
{
  "mcpServers": {
    "hugegraph": {
      "command": "uvx",
      "args": ["--from", "hugegraph-mcp==1.7.0", "hugegraph-mcp"],
      "env": {
        "HUGEGRAPH_URL": "http://hugegraph.example.com:8080",
        "HUGEGRAPH_GRAPH_PATH": "DEFAULT/hugegraph",
        "HUGEGRAPH_USER": "admin",
        "HUGEGRAPH_PASSWORD": "admin",
        "HUGEGRAPH_MCP_READONLY": "true"
      }
    }
  }
}
```

## 开发者说明

从代码仓运行：

```bash
export PYTHONPATH=/Users/uleng/Code/hugegraph-ai-pr73-mcp/hugegraph-mcp:/Users/uleng/Code/hugegraph-ai-pr73-mcp/hugegraph-python-client/src
/Users/uleng/Code/hugegraph-ai-pr73-mcp/.venv/bin/python -m hugegraph_mcp.server
```

此命令使用代码仓已有的根目录虚拟环境，并强制从当前 checkout 加载
`hugegraph-mcp` 和同仓的 Python client。它不会让 uv 单独解析
`hugegraph-mcp` 子项目，因此不会错误地从包索引解析
`hugegraph-python-client>=1.7.0`，而会直接使用相邻源码。

MCP 层负责稳定工具、运行时配置、权限、结构化请求校验、写入计划及回执持久化，并把图操作交给 HugeGraph Server，把已启用的 AI 操作交给 HugeGraph-AI。

## 对外工具面

默认 `v2_core` 契约注册 16 个工具。`v1` 兼容契约注册 10 个工具，不包含六个 v2 新增工具。

| 工具 | 契约 | 说明 |
|------|------|------|
| `inspect_graph_tool` | v1、v2 | 查看连接、schema 摘要、只读状态和工具契约 |
| `generate_gremlin_tool` | v1、v2 | 生成 Gremlin；在硬资源预算合同验证前禁止执行 |
| `execute_gremlin_read_tool` | v1、v2 | 为兼容保留注册；公开 Raw Gremlin 执行当前返回 `FEATURE_DISABLED` |
| `extract_graph_data_tool` | v1、v2 | 抽取候选图数据，不写图 |
| `design_schema_tool` | v1、v2 | 提供 schema 设计建议 |
| `apply_schema_tool` | v1、v2 | 校验或预览一个 schema create；v2 支持确认执行 |
| `import_graph_data_tool` | v1、v2 | 校验并预览结构化点边创建；确认当前返回 `FEATURE_DISABLED` |
| `delete_graph_data_tool` | v1、v2 | 预览精确删除；支持确认删除边 |
| `refresh_vid_embeddings_tool` | v1、v2 | 管理写工具，仅在 admin mode 与写入均启用时开放 |
| `execute_gremlin_write_tool` | v1、v2 | 为兼容保留注册；公开 Raw Gremlin 执行当前返回 `FEATURE_DISABLED` |
| `inspect_schema_tool` | v2 | 查看并筛选 schema 对象及关系 |
| `query_graph_data_tool` | v2 | 执行类型化、有界的点边读取 |
| `mutate_graph_properties_tool` | v2 | 预览属性变更；缺少原子 CAS 时禁止确认 |
| `confirm_write_tool` | v2 | 仅通过 `plan_id` 确认一个持久化计划 |
| `get_write_status_tool` | v2 | 仅通过 `plan_id` 查询计划及操作的持久化结果 |
| `reconcile_write_tool` | v2 | 仅通过 `plan_id` 和只读检查协调 `UNKNOWN` 或 `PARTIAL` 结果 |

非法 `HUGEGRAPH_MCP_TOOLSET` 值会收口到 `v1`。工具注册在进程启动时确定，修改工具集后需要重启服务。

## 统一响应格式

高层工具返回：

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "warnings": [],
  "next_actions": [],
  "meta": {
    "request_id": "req-...",
    "graph": "hugegraph",
    "graphspace": "DEFAULT",
    "readonly": true,
    "duration_ms": 12.3
  }
}
```

失败响应设置 `ok=false`。调用方必须遵守稳定的 `error.type` 和 `error.retryable`。

## 写入安全合同

规范写入流程仅使用服务端签发的 `plan_id`：

```text
结构化 dry-run
  -> 审查具体目标、警告和变更摘要
  -> 获取持久化不可变 plan_id
  -> confirm_write_tool(plan_id)
  -> get_write_status_tool(plan_id)
  -> 必要时 reconcile_write_tool(plan_id)
```

确认调用不接收原始 payload，持久化计划是唯一执行依据。每个操作都有持久化回执；再次提交已经完成的 `plan_id` 时返回已记录结果，不会再次写入。

`APPLIED` 表示全部操作均已证明写入成功。`PARTIAL` 表示至少一个操作已写入，但整个 workflow 未完全成功。`UNKNOWN` 表示服务无法证明某个操作是否已经提交；调用方必须查询状态并执行 reconcile，禁止盲目重复写入。

旧的 `plan_hash`、`nonce`、`expires_at` locator 只在 plan-ID 合同引入后的首个兼容版本中保留于 legacy 写入入口。这三个字段必须同时提供，不得与 `plan_id` 混用，并会返回 `LEGACY_CONFIRMATION_DEPRECATED` 警告。新集成必须调用 `confirm_write_tool(plan_id)`。

内置 SQLite plan store 只适用于单个可写 MCP 实例。多实例部署前必须提供共享事务存储；当前使用 SQLite 且 `HUGEGRAPH_MCP_WRITE_INSTANCE_COUNT` 大于一时会 fail closed。

### 操作边界

- 可确认的 schema plan 只能包含一个 `create_property_key`、`create_vertex_label` 或 `create_edge_label`。成功状态为 `APPLIED`。索引创建、append/eliminate 和 drop 不在 apply 范围内。
- 图导入始终仅支持预览，因为 HugeGraph 1.7.0 的原子 create-if-absent 能力尚未得到验证。预览返回 `confirmable=false`、`preview_only=true`，不签发 `plan_id`；确认返回 `FEATURE_DISABLED` 且不写入。
- 属性变更仅支持预览。HugeGraph 1.7.0 没有原子 compare-and-set 属性更新，确认请求返回 `FEATURE_DISABLED`。
- 孤立点删除仅支持预览。Docker 并发测试已证明 HugeGraph 1.7.0 无法原子保证“仅在没有关联边时删除”；确认请求返回 `FEATURE_DISABLED`。请显式删除关联边，再通过独立受控维护路径处理顶点。
- 精确边删除可确认，因为计划绑定了具体 edge ID。

Schema 和图数据 dry-run 在操作数超过 200 或 payload 超过 1 MiB 时会拒绝返回可用预览或计划。

### Raw Gremlin 边界

所有公开 Raw Gremlin 执行路径均被禁用，包括 `execute_gremlin_read_tool`、`execute_gremlin_write_tool` 和 `generate_gremlin_tool(execute=true)`。admin mode 不能绕过此限制。只有部署环境证明服务端 evaluation/wait timeout、服务端结果条数上限、客户端流式字节上限以及只读 principal 全部可用后，才可开放 Raw Gremlin 执行。响应完整落入内存后的条数或字节检查只是输出保护，不构成硬资源预算。

结构化读取与 `generate_gremlin_tool(execute=false)` 仍可使用。

## 配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `HUGEGRAPH_URL` | `http://127.0.0.1:8080` | HugeGraph Server URL |
| `HUGEGRAPH_GRAPH_PATH` | `DEFAULT/hugegraph` | `GRAPH_SPACE/GRAPH_NAME` |
| `HUGEGRAPH_GRAPHSPACE`、`HUGEGRAPH_GRAPH` | 未设置 | 显式值会覆盖 `HUGEGRAPH_GRAPH_PATH` |
| `HUGEGRAPH_USER` | `admin` | HugeGraph 用户名 |
| `HUGEGRAPH_PASSWORD` | 空 | HugeGraph 密码 |
| `HUGEGRAPH_MCP_TOOLSET` | `v2_core` | `v1` 或 `v2_core`；非法值回落到 `v1` |
| `HUGEGRAPH_MCP_READONLY` | `true` | 为 true 时禁止全部受控写入 |
| `HUGEGRAPH_MCP_ALLOW_AI` | `false` | 是否允许调用 HugeGraph-AI |
| `HUGEGRAPH_MCP_ADMIN_MODE` | `false` | 是否启用符合条件的管理/调试工具 |
| `HUGEGRAPH_AI_URL` | `http://127.0.0.1:8001` | HugeGraph-AI URL |
| `HUGEGRAPH_AI_TOKEN` | 未设置 | 可选的 HugeGraph-AI bearer token |
| `HUGEGRAPH_AI_GRAPH_URL` | 未设置 | 提供给 HugeGraph-AI 的图 URL；默认使用 `HUGEGRAPH_URL` |
| `HUGEGRAPH_CONNECT_TIMEOUT_SECONDS` | `0.5` | HugeGraph 连接超时；范围 `0.001..86400` |
| `HUGEGRAPH_READ_TIMEOUT_SECONDS` | `15` | 结构化 HugeGraph 读取超时；范围 `0.001..86400` |
| `HUGEGRAPH_WRITE_TIMEOUT_SECONDS` | `15` | HugeGraph 数据与 schema 写入超时；范围 `0.001..86400` |
| `HUGEGRAPH_AI_TIMEOUT_SECONDS` | `30` | HugeGraph-AI HTTP 超时；范围 `1..86400` |
| `HUGEGRAPH_MCP_TIMEOUT_SECONDS` | `30` | AI 超时的废弃兼容配置 |
| `HUGEGRAPH_MCP_MAX_RESULT_ITEMS` | `100` | 响应完整落入内存后的条数保护；范围 `1..1000000` |
| `HUGEGRAPH_MCP_MAX_RESULT_BYTES` | `1048576` | 响应完整落入内存后的字节保护；范围 `1..1073741824` |
| `HUGEGRAPH_MCP_PLAN_STORE` | `sqlite` | 持久化 plan store；当前仅支持 `sqlite` |
| `HUGEGRAPH_MCP_WRITE_INSTANCE_COUNT` | `1` | 可写 MCP 实例数；SQLite 要求精确为一 |
| `HUGEGRAPH_MCP_STATE_DIR` | `$XDG_STATE_HOME/hugegraph-mcp` 或 `~/.local/state/hugegraph-mcp` | plan、operation 与 receipt 数据库目录 |

布尔值不区分大小写，支持 `1/true/yes/on` 和 `0/false/no/off`。非法值采用安全默认值；非法、非有限或越界的数值采用文档默认值。

推荐默认配置为 `HUGEGRAPH_MCP_READONLY=true`、`HUGEGRAPH_MCP_ALLOW_AI=false`、`HUGEGRAPH_MCP_ADMIN_MODE=false`。

## License

Apache License 2.0
