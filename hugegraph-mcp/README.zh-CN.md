# HugeGraph MCP

[English](README.md)

HugeGraph MCP 是 HugeGraph 的 Model Context Protocol Server。它的定位是安全、可控的薄适配层：对外暴露少量稳定工具，内部统一处理配置、权限、只读 Gremlin 校验、dry-run/confirm 写入安全链和统一响应格式。

**要求 HugeGraph Server >= 1.7.0**（MCP 默认使用 `graphspace=DEFAULT` 并依赖 graphspace 路由 API，旧版本不支持）。

## 快速开始

请先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，设置连接变量后通过 `uvx` 运行 HugeGraph MCP。请将 `hugegraph.example.com` 替换为实际的 HugeGraph Server 主机名：

```bash
export HUGEGRAPH_URL=http://hugegraph.example.com:8080
export HUGEGRAPH_GRAPH_PATH=DEFAULT/hugegraph
export HUGEGRAPH_USER=admin
export HUGEGRAPH_PASSWORD=admin
export HUGEGRAPH_MCP_READONLY=true

uvx --from hugegraph-mcp==1.7.0 hugegraph-mcp
```

进程通过 stdout 输出 MCP JSON-RPC，请由 MCP 客户端连接。除非已经有明确的写入验证计划，否则保持
`HUGEGRAPH_MCP_READONLY=true`。默认工具集是 `v2_core`；旧客户端需要 10 工具兼容契约时，在启动前设置
`HUGEGRAPH_MCP_TOOLSET=v1`。

对于支持 JSON Server 配置的 MCP 客户端，可使用 `uvx` 作为启动命令：

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

### 从源码运行

在仓库根目录执行：

```bash
uv venv
uv pip install -e ../hugegraph-python-client -e .
uv run --project hugegraph-mcp hugegraph-mcp
```

### 设计边界

HugeGraph MCP 不把 MCP 做成另一套业务内核。MCP 层负责：

- 暴露稳定 MCP 工具接口
- 读取运行时配置
- 执行权限和 readonly guard
- 校验 Gremlin 是否只读
- 生成并校验 `plan_hash`
- 统一响应 envelope
- 将 AI 能力转发给 HugeGraph-AI，或将图读写转发给 HugeGraph Server



### 对外工具面

默认 `v2_core` 工具集注册 13 个 MCP 工具：其中 11 个是普通用户稳定工具，另外 2 个是管理/调试工具，默认注册但受 admin mode 阻断。

普通用户稳定工具包括：

- `inspect_graph_tool`
- `inspect_schema_tool`
- `query_graph_data_tool`
- `generate_gremlin_tool`
- `execute_gremlin_read_tool`
- `extract_graph_data_tool`
- `design_schema_tool`
- `apply_schema_tool`
- `mutate_graph_properties_tool`
- `import_graph_data_tool`
- `delete_graph_data_tool`

以下工具仍注册在 MCP 中，但属于管理/调试能力，默认受 `HUGEGRAPH_MCP_ADMIN_MODE=false` 阻断。具备写入能力的管理工具还要求 `HUGEGRAPH_MCP_READONLY=false`：

- `execute_gremlin_write_tool`
- `refresh_vid_embeddings_tool`

`execute_gremlin_write_tool` 是写入安全链唯一的 break-glass（紧急直通）例外。它不提供预览、dry-run、plan hash 或确认步骤，可直接执行任意 Gremlin 写语句。只能在隔离且仅受信管理员可访问的 transport 上启用，禁止在共享 Agent 或客户端端点启用。

### 工具集选择

`HUGEGRAPH_MCP_TOOLSET` 控制对外工具契约：

| 取值 | 工具数 | 用途 |
|------|------:|------|
| `v1` | 10 | 兼容旧客户端；只暴露原有稳定工具和管理/调试工具，隐藏三个 `v2_core` 新工具，并保持 `apply_schema_tool(mode="apply")` 禁用 |
| `v2_core` | 13 | 新部署默认值；在 V1 工具基础上增加 `inspect_schema_tool`、`query_graph_data_tool`、`mutate_graph_properties_tool`，并启用 P0a 范围内的 schema create apply 路径 |

未设置 `HUGEGRAPH_MCP_TOOLSET` 时，服务默认使用 `v2_core`。除精确的 `v1` 之外，其他取值都会按 `v2_core` 处理。
工具集选择在 MCP server 启动并注册工具时生效；修改该变量后需要重启 MCP server。


### 统一响应格式

高层工具返回统一 envelope：

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

失败时 `ok=false`，`error` 使用统一结构：

```json
{
  "type": "READONLY_VIOLATION",
  "message": "DATA_WRITE capability is disabled in read-only mode",
  "suggestion": "Disable HUGEGRAPH_MCP_READONLY to allow this operation.",
  "retryable": false,
  "source": "hugegraph-mcp",
  "details": {}
}
```


## 工具参考

### 用户可用工具总览

| 工具 | 说明 |
|------|------|
| `inspect_graph_tool` | 查看 HugeGraph Server 状态、schema 摘要、点边计数、readonly 状态、AI 可用性和当前 MCP 工具契约字段 |
| `inspect_schema_tool` | 查看 schema 对象、关系和索引标签；支持按 property key、vertex label、edge label 或 index label 过滤 |
| `query_graph_data_tool` | 通过类型化操作查询点或边（`get_by_id`、`get_by_ids`、`page`、`condition`），有显式 limit，不自动降级为 Gremlin 全图扫描 |
| `generate_gremlin_tool` | 根据自然语言生成 Gremlin；默认只生成，不执行；`execute=true` 时也必须通过只读校验 |
| `execute_gremlin_read_tool` | 执行只读 Gremlin 查询；无法确认安全时拒绝执行，并支持 `limit_policy` 处理无界读取 |
| `extract_graph_data_tool` | 从自然语言文本抽取候选图数据，返回点和边结构，不写入 HugeGraph |
| `import_graph_data_tool` | 结构化图数据导入入口；真实写入必须经过 `dry_run -> plan_hash -> confirm` |
| `delete_graph_data_tool` | 受控删除入口；只支持精确删除点或边，不支持条件批量删除和级联删除 |
| `design_schema_tool` | 根据 schema 操作草案给出设计建议，不修改数据库 |
| `apply_schema_tool` | 校验 schema 操作并 dry-run P0a apply 范围；`v2_core` 中 dry-run 和确认后的 `apply` 只支持 `create_property_key`、`create_vertex_label`、`create_edge_label`；`v1` 中真实 `apply` 仍禁用 |
| `mutate_graph_properties_tool` | 对单个精确点或边追加/淘汰属性；两种操作都必须经过 `dry_run -> plan_hash -> confirm`，目标变更时拒绝执行 |
| `execute_gremlin_write_tool` | 直接执行 Gremlin 写语句；默认禁用，仅 `HUGEGRAPH_MCP_ADMIN_MODE=true` 且 `HUGEGRAPH_MCP_READONLY=false` 时可用 |
| `refresh_vid_embeddings_tool` | 刷新 VID embeddings，会改变索引状态；默认禁用，仅 `HUGEGRAPH_MCP_ADMIN_MODE=true` 且 `HUGEGRAPH_MCP_READONLY=false` 时可用 |

Schema apply 使用闭合的操作字段契约。PropertyKey 支持
`data_type`、`cardinality`、`aggregate_type`、`user_data`；VertexLabel 支持
`id_strategy`、`properties`、`primary_keys`、`nullable_keys`、`index_labels`、
`enable_label_index`、`user_data`；EdgeLabel 支持 `source_label`、`target_label`、
`properties`、`nullable_keys`、`sort_keys`、`frequency`、`enable_label_index`、
`user_data`。未列出的字段（包括 `ttl*`）会在签发 plan 前的校验阶段拒绝。
支持的字段会转发到 HugeGraph，并通过 live schema 回读核对。




## 写入安全链

所有普通用户可触达的写操作都必须经过以下安全链。上文所述仅管理员可用的 `execute_gremlin_write_tool` break-glass 例外不经过此链：

```text
dry_run=true
  -> 用户/agent 审查 preview、warnings、matched_count、mutation_summary
  -> 记录 plan_hash、nonce、expires_at
  -> dry_run=false + confirm=true + 原始 payload + plan_hash + nonce + expires_at
  -> MCP 重新校验目标、权限、schema、payload digest 和过期时间
  -> 执行写入
  -> 返回写入/删除结果和失败明细
```

`plan_hash` 不是简单的 payload 哈希。它至少绑定：

- 工具名
- 操作 mode
- graph url
- graph name
- graph space
- MCP readonly 状态
- 当前 schema hash
- normalized payload digest
- nonce
- expiry

confirm 阶段必须全量重验。dry-run 结果过期、目标图变化、schema 变化、payload 变化或权限变化时，confirm 必须失败并要求重新 dry-run。

### 导入语义

`import_graph_data_tool(mode="ingest")` 是 `v2_core` 与 `v1` 兼容工具集共用的结构化导入路径。它使用本地 schema 校验、dry-run/hash/confirm 和 `manage_graph_data()` 的 direct Gremlin 写入；不会调用 HugeGraph-AI `/graph-import` HTTP 路径。legacy/internal 的 AI-backed 函数命名为 `ingest_graph_data_via_ai()`。

`import_graph_data_tool(mode="ingest")` 执行创建时返回三类状态：

- `success`：全部写入成功
- `partial` / `degraded`：部分写入成功，部分失败或结果不可完全确认
- `error`：写入失败

响应需要包含已写数量、失败明细和可补偿建议，避免出现“半写半崩但不可追踪”。

#### 边端点契约

边端点同时支持 object 和 scalar 写法：

```text
object source/target  -> 原样透传
  {"id": "1:Alice"}   -> 按 HugeGraph vertex id 匹配
  {"name": "Alice"}   -> 按完整主键匹配；任意属性匹配不属于 public graph_data 契约

scalar source/target  -> 如果 live schema 中该端点 label 恰好是单主键，
                         优先按该主键匹配；否则回退为 {"id": value}

outV / inV / payload 中显式 vertex id -> 始终表示 HugeGraph vertex id，
                                        不做主键改写
```

scalar 端点是 same-payload import 的便捷写法，但在单主键 live schema 下会按主键解析，可能匹配图中已存在的顶点；它不只在当前 payload 内查找。因此 edge-only 或连接 payload 外已有顶点的输入是合法的，前提是 dry-run 的 live match 能把每个端点唯一解析到一个顶点。

### 删除语义

`delete_graph_data_tool` 的删除是受控删除：

- dry-run 阶段必须查出将被删除的具体对象
- confirm 阶段必须重新匹配并校验目标一致
- 删除后必须反查确认目标不存在
- 顶点有关联边时默认拒绝删除

因此，删除一个有关联边的点时，应先 dry-run 并删除相关边，再 dry-run 并删除该点。

## 配置说明

所有配置通过环境变量读取。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HUGEGRAPH_URL` | `http://127.0.0.1:8080` | HugeGraph Server 地址 |
| `HUGEGRAPH_GRAPH_PATH` | `DEFAULT/hugegraph` | 图路径，格式为 `GRAPH_SPACE/GRAPH_NAME` |
| `HUGEGRAPH_GRAPHSPACE` | 未设置 | 单独覆盖 graph space |
| `HUGEGRAPH_GRAPH` | 未设置 | 单独覆盖 graph name |
| `HUGEGRAPH_USER` | `admin` | HugeGraph 用户名 |
| `HUGEGRAPH_PASSWORD` | `""` | HugeGraph 密码 |
| `HUGEGRAPH_MCP_TOOLSET` | `v2_core` | 对外工具契约：`v1` 为 10 工具兼容模式，`v2_core` 为 13 工具默认模式 |
| `HUGEGRAPH_MCP_READONLY` | `true` | 是否启用只读模式 |
| `HUGEGRAPH_MCP_ALLOW_AI` | `false` | 是否允许调用 HugeGraph-AI |
| `HUGEGRAPH_MCP_ADMIN_MODE` | `false` | 是否启用管理/调试工具 |
| `HUGEGRAPH_AI_URL` | `http://127.0.0.1:8001` | HugeGraph-AI 地址 |
| `HUGEGRAPH_AI_TOKEN` | 未设置 | HugeGraph-AI 开启认证时使用的 Bearer Token；公开 MCP 工具通过环境变量配置（内部 HTTP 调用方可按请求覆盖） |
| `HUGEGRAPH_AI_GRAPH_URL` | 未设置 | AI 侧使用的图地址，未设置时使用 `HUGEGRAPH_URL` |
| `HUGEGRAPH_MCP_TIMEOUT_SECONDS` | `30` | AI 调用超时时间 |
| `HUGEGRAPH_MCP_MAX_REPEAT_TIMES` | `10` | `repeat().times(n)` 只读成本 warning 的建议最大值 |
| `HUGEGRAPH_MCP_STATE_DIR` | `$XDG_STATE_HOME/hugegraph-mcp`；未设置 `XDG_STATE_HOME` 时为 `~/.local/state/hugegraph-mcp` | 持久化一次性确认账本的本地状态目录 |

`HUGEGRAPH_MCP_TIMEOUT_SECONDS` 仅作用于 HugeGraph-AI HTTP 调用，不作用于 PyHugeClient 的 Gremlin 查询。只读 Gremlin 的成本边界由 read cost guard 以非阻塞 warning 形式提示，包括裸全图扫描、`repeat()` 无 `times()` 上限、以及 `path` / `group` / `profile` 无 `limit` 或 `range`。

Boolean 配置只接受 `1`、`true`、`yes`、`on` 和 `0`、`false`、`no`、`off`，忽略大小写和首尾空白。空值或非法值会 fail closed：`HUGEGRAPH_MCP_READONLY` 保持开启，`HUGEGRAPH_MCP_ALLOW_AI` 和 `HUGEGRAPH_MCP_ADMIN_MODE` 保持关闭。

确认账本记录服务端签发的 dry-run 计划和已消费 nonce 的摘要。confirm 只接受匹配的服务端签发计划，执行服务端 10 分钟最大 TTL，并通过原子消费保证一个写计划在本地进程重启后以及共享同一状态目录的多个 worker 之间最多使用一次。POSIX 平台上，HugeGraph MCP 将状态目录权限限制为 `0700`，账本数据库权限限制为 `0600`。状态无法安全持久化时，写入会在执行前被阻断。

推荐默认安全姿态：

- `HUGEGRAPH_MCP_READONLY=true`
- `HUGEGRAPH_MCP_ALLOW_AI=false`
- `HUGEGRAPH_MCP_ADMIN_MODE=false`

常见组合：

| 场景 | 配置 |
|------|------|
| 只读图查询 | `HUGEGRAPH_MCP_READONLY=true`，`HUGEGRAPH_MCP_ALLOW_AI=false` |
| AI 生成只读 Gremlin / 文本抽取 | `HUGEGRAPH_MCP_READONLY=true`，`HUGEGRAPH_MCP_ALLOW_AI=true` |
| 允许受控导入和删除 | `HUGEGRAPH_MCP_READONLY=false`，按需设置 `HUGEGRAPH_MCP_ALLOW_AI=true` |
| 管理/调试 | `HUGEGRAPH_MCP_READONLY=false`，`HUGEGRAPH_MCP_ADMIN_MODE=true` |

## License

Apache License 2.0
