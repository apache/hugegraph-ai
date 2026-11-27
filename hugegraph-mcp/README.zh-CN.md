# HugeGraph MCP

[English](README.md)

HugeGraph MCP 是 HugeGraph Server 的安全、可控 Model Context Protocol 适配层。它提供稳定的结构化工具，统一执行配置和权限检查，并持久化不可变写入计划与执行结果。

**要求 HugeGraph Server >= 1.7.0。** 默认图路径是 `DEFAULT/hugegraph`，依赖旧版本不具备的 graphspace 路由 API。

## 快速开始

安装已发布版本不需要克隆仓库。以下命令面向当前仓库准备的发行版本，正式发布到 PyPI 后才可使用。
发布前请使用[开发者说明](#开发者说明)中的源码方式验证。
本次发行使用 `core`／`legacy`；上一版 `1.7.1` 使用 `v2_core`／`v1`。
发布步骤见[发布流程](docs/releasing.md)。

安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后以只读模式启动：

```bash
export HUGEGRAPH_URL=http://hugegraph.example.com:8080
export HUGEGRAPH_GRAPH_PATH=DEFAULT/hugegraph
export HUGEGRAPH_USER=admin
export HUGEGRAPH_PASSWORD=admin
export HUGEGRAPH_MCP_READONLY=true

uvx hugegraph-mcp@1.8.0
```

进程通过 stdout 提供 MCP JSON-RPC。除非明确需要受控写入，请保持 `HUGEGRAPH_MCP_READONLY=true`。不设置 `HUGEGRAPH_MCP_TOOLSET` 即使用默认 `core` 工具集。需要 10 工具的兼容工具集时使用 `legacy`；从 `1.7.1` 升级请参考下文的工具集命名与迁移说明。

支持 JSON Server 配置的 MCP 客户端可使用：

```json
{
  "mcpServers": {
    "hugegraph": {
      "command": "uvx",
      "args": ["hugegraph-mcp@1.8.0"],
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

源码试用可在仓库根目录运行同一 checkout 的两个包：

```bash
uvx --no-config --no-cache --with ./hugegraph-python-client --from ./hugegraph-mcp hugegraph-mcp
```

从 PR checkout 的仓库根目录执行。安装 uv 后，创建独立环境并安装同分支的 MCP 与客户端：

```bash
uv venv --python 3.12 .venv-mcp
uv --no-config pip install --python .venv-mcp -e ./hugegraph-python-client -e ./hugegraph-mcp
```

使用上方环境变量配置实际的 HugeGraph 地址和凭据，然后启动（macOS/Linux）：

```bash
.venv-mcp/bin/python -m hugegraph_mcp.server
```

Windows PowerShell：

```powershell
.\.venv-mcp\Scripts\python.exe -m hugegraph_mcp.server
```

此安装使用当前 checkout 的两个包，不依赖作者机器上的路径或已有虚拟环境。`--no-config` 避免把根目录的 LLM 依赖约束应用于独立 MCP 环境。

在 MCP 客户端配置中，将 `command` 设为自己 checkout 下此 Python 解释器的绝对路径，`args` 设为 `["-m", "hugegraph_mcp.server"]`。

连接后先调用 `inspect_graph_tool(include_raw_schema=true)`，确认 `hugegraph_server_status="available"`，再对已有标签执行有界结构化查询（将 `person` 替换为实际标签）：

```json
{"name":"query_graph_data_tool","arguments":{"target":"vertex","operation":"page","label":"person","limit":5}}
```

[架构与规划](docs/architecture.md) · [完整集成检查](docs/integration.md) · [发布顺序](docs/releasing.md)

使用 MCP Inspector 可以验证连接，并调用 `inspect_graph_tool(include_counts=true)` 查看图状态：

![MCP Inspector 查看图状态](https://raw.githubusercontent.com/hugegraph/hugegraph-ai/fb6a3d91c26fc82cc4e0a98667e9d49418659bcf/docs/images/mcp/inspector.png)

结构化查询的 `limit` 默认是 `100`，输入必须是 `1–500` 的整数；超过 `500` 返回 `VALIDATION_ERROR`。合法值再按 `HUGEGRAPH_MCP_MAX_RESULT_ITEMS` 收紧，例如配置上限为 `50` 时，请求 `100` 实际使用 `50`。超过有效上限的 ID 批次会在查询前被拒绝。返回结果超过条数或字节上限时整体拒绝，不截断结果或返回后续游标；这些检查不限制服务端执行量或传输期间的内存占用。

## 对外工具面

默认 `core` 工具集注册 16 个工具。`legacy` 兼容工具集注册 10 个工具，不包含六个 core 专属工具。工具已注册不代表其所有操作都已启用。

| 工具 | 工具集 | 说明 |
|------|------|------|
| `inspect_graph_tool` | legacy、core | 查看连接、schema 摘要、只读状态和工具契约 |
| `generate_gremlin_tool` | legacy、core | 生成 Gremlin；在硬资源预算合同验证前禁止执行 |
| `execute_gremlin_read_tool` | legacy、core | 为兼容保留注册；公开 Raw Gremlin 执行当前返回 `FEATURE_DISABLED` |
| `extract_graph_data_tool` | legacy、core | 抽取候选图数据，不写图 |
| `design_schema_tool` | legacy、core | 提供 schema 设计建议 |
| `apply_schema_tool` | legacy、core | 校验或预览一个 schema create；core 支持确认执行 |
| `import_graph_data_tool` | legacy、core | 校验并预览结构化点边创建；确认当前返回 `FEATURE_DISABLED` |
| `delete_graph_data_tool` | legacy、core | 预览精确删除；支持确认删除边 |
| `refresh_vid_embeddings_tool` | legacy、core | 管理写工具，仅在 admin mode 与写入均启用时开放 |
| `execute_gremlin_write_tool` | legacy、core | 为兼容保留注册；公开 Raw Gremlin 执行当前返回 `FEATURE_DISABLED` |
| `inspect_schema_tool` | core | 查看并筛选 schema 对象及关系 |
| `query_graph_data_tool` | core | 执行类型化、有界的点边读取 |
| `mutate_graph_properties_tool` | core | 预览属性变更；缺少原子 CAS 时禁止确认 |
| `confirm_write_tool` | core | 仅通过 `plan_id` 确认一个持久化计划 |
| `get_write_status_tool` | core | 仅通过 `plan_id` 查询计划及操作的持久化结果 |
| `reconcile_write_tool` | core | 仅通过 `plan_id` 和只读检查协调 `UNKNOWN` 或 `PARTIAL` 结果 |

空白或未知的 `HUGEGRAPH_MCP_TOOLSET` 值会导致启动报错；未设置时使用 `core`。工具注册在进程启动时确定，修改工具集后需要重启服务。

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

## 工具集命名与迁移

`core` 和 `legacy` 选择同一个包内的工具分组，不是包发行版本、HugeGraph Server
版本或 MCP 协议版本。两种工具集都返回 `mcp_tool_contract_version="2.0"`，
选择较小的工具集不会改变工具契约版本。

从 `1.7.1` 升级时：

- 将 `HUGEGRAPH_MCP_TOOLSET=v2_core` 改成 `core`，将 `v1` 改成 `legacy`。
  旧值仍作为已弃用的输入别名接受，启动时记录迁移警告，不维护独立实现。
- `inspect_graph_tool` 的 `data.toolset` 和 `meta.toolset` 只返回 `core` 或
  `legacy`，即使输入的是旧别名。比较这些字段的客户端需要更新；不新增第二个同义字段。
- 不设置变量即使用默认值。空白或未知值（包括 `v2`）现在会阻止启动，不再自动回落到兼容工具集。
- 修改配置后需要重启。工具注册、行为分支和状态报告使用同一个启动时选择结果。

兼容性新增功能加入 `core`，不会因为增加工具而创建新的编号工具集。`legacy` 保留
兼容接口并接受必要修复。破坏性工具变更或未来移除别名，需要明确迁移说明并遵循项目
发行兼容流程；本次不设定别名移除时间。两种工具集都不会绕过 readonly、AI、admin
或后端能力检查。

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

结构化读取仍可使用。`generate_gremlin_tool(execute=false)` 还需要 `HUGEGRAPH_MCP_ALLOW_AI=true` 和已配置的 AI 服务。

## 配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `HUGEGRAPH_URL` | `http://127.0.0.1:8080` | HugeGraph Server URL |
| `HUGEGRAPH_GRAPH_PATH` | `DEFAULT/hugegraph` | `GRAPH_SPACE/GRAPH_NAME` |
| `HUGEGRAPH_GRAPHSPACE`、`HUGEGRAPH_GRAPH` | 未设置 | 显式值会覆盖 `HUGEGRAPH_GRAPH_PATH` |
| `HUGEGRAPH_USER` | `admin` | HugeGraph 用户名 |
| `HUGEGRAPH_PASSWORD` | 空 | HugeGraph 密码 |
| `HUGEGRAPH_MCP_TOOLSET` | `core` | `core` 或 `legacy`；空白或未知值导致启动失败 |
| `HUGEGRAPH_MCP_READONLY` | `true` | 为 true 时禁止全部受控写入 |
| `HUGEGRAPH_MCP_ALLOW_AI` | `false` | 是否允许调用 HugeGraph-AI |
| `HUGEGRAPH_MCP_ADMIN_MODE` | `false` | 是否启用符合条件的管理/调试工具 |
| `HUGEGRAPH_AI_URL` | `http://127.0.0.1:8001` | HugeGraph-AI URL |
| `HUGEGRAPH_AI_TOKEN` | 未设置 | 可选的 HugeGraph-AI bearer token |
| `HUGEGRAPH_AI_GRAPH_URL` | 未设置 | 已弃用且不生效；请在 AI 服务侧配置 `GRAPH_URL` |
| `HUGEGRAPH_CONNECT_TIMEOUT_SECONDS` | `0.5` | HugeGraph 连接超时；范围 `0.001..86400` |
| `HUGEGRAPH_READ_TIMEOUT_SECONDS` | `15` | 结构化 HugeGraph 读取超时；范围 `0.001..86400` |
| `HUGEGRAPH_WRITE_TIMEOUT_SECONDS` | `15` | HugeGraph 数据与 schema 写入超时；范围 `0.001..86400` |
| `HUGEGRAPH_AI_TIMEOUT_SECONDS` | `30` | HugeGraph-AI HTTP 超时；范围 `1..86400` |
| `HUGEGRAPH_MCP_TIMEOUT_SECONDS` | `30` | AI 超时的废弃兼容配置 |
| `HUGEGRAPH_MCP_MAX_RESULT_ITEMS` | `100` | 响应完整落入内存后的条数保护；范围 `1..1000000` |
| `HUGEGRAPH_MCP_MAX_RESULT_BYTES` | `1048576` | 响应完整落入内存后的字节保护；范围 `1..1073741824` |
| `HUGEGRAPH_MCP_MAX_REPEAT_TIMES` | `10` | `repeat().times(n)` 的深度超过该值时给出 Gremlin 成本警告，警告不拦截查询 |
| `HUGEGRAPH_MCP_PLAN_STORE` | `sqlite` | 持久化 plan store；当前仅支持 `sqlite` |
| `HUGEGRAPH_MCP_WRITE_INSTANCE_COUNT` | `1` | 可写 MCP 实例数；SQLite 要求精确为一 |
| `HUGEGRAPH_MCP_STATE_DIR` | `$XDG_STATE_HOME/hugegraph-mcp` 或 `~/.local/state/hugegraph-mcp` | plan、operation 与 receipt 数据库目录 |

布尔值不区分大小写，支持 `1/true/yes/on` 和 `0/false/no/off`。非法值采用安全默认值；非法、非有限或越界的数值采用文档默认值。

推荐默认配置为 `HUGEGRAPH_MCP_READONLY=true`、`HUGEGRAPH_MCP_ALLOW_AI=false`、`HUGEGRAPH_MCP_ADMIN_MODE=false`。

### AI 服务配置

设置 `HUGEGRAPH_MCP_ALLOW_AI=true`、可访问的 `HUGEGRAPH_AI_URL`，并在 AI 服务启用 bearer 认证时设置
`HUGEGRAPH_AI_TOKEN`。在 AI 服务自身配置 `GRAPH_URL`、`GRAPH_NAME` 和 `GRAPH_SPACE`：地址必须能从
AI 服务访问，例如 Docker 内的 `http://server:8080`；图名与 graphspace 必须与 MCP 目标一致。
修改 MCP 的 `HUGEGRAPH_URL` 不会重新配置 AI 服务；`HUGEGRAPH_AI_GRAPH_URL` 不生效，不能用于覆盖 AI 目标。
使用 MCP 默认目标 `DEFAULT/hugegraph` 时，请设置 AI 的 `GRAPH_NAME=hugegraph`。
目标校验将 AI 侧未设置、null、空字符串或全空白的 graphspace 视为 `GRAPH_SPACE=DEFAULT`；
该比较不修改保存的配置，也不改变现有向量索引路径约定。

刷新需要 MCP 允许写入、启用管理模式、启用 AI，并在调用时设置 `confirm=true`。当前 AI 源码还要求服务侧
`ENABLE_LOGIN=true`、`HUGEGRAPH_LLM_ENABLE_THIN_WRITES=true`，配置强 `USER_TOKEN`，并通过 MCP 的
`HUGEGRAPH_AI_TOKEN` 传入。上述 AI 写入门禁适用于当前实现；旧部署可能没有这些门禁，必须核对实际服务版本，
不能假设所有 AI 部署都实现了相同的门禁。

当前 MCP 刷新路径先检查 `GET /vid-embeddings/refresh-capabilities` 返回的 `protocol_version=1`，
再向 `POST /v1/vid-embeddings/refresh` 传入两个必填目标字段，在同一配置锁内完成目标校验与刷新。
滚动升级时，能力探测与 POST 可能落到不同副本，因此安全边界是版本化 POST 路由。
旧副本缺少该路由时，MCP 会提示升级 AI，绝不回退到 `POST /vid-embeddings/refresh`。
旧路由为兼容已有调用方，仍允许已认证且开启写入的调用方传入空请求。

此校验只确认图名和 graphspace，不证明 MCP 与 AI 连接的是同一台物理服务器；部署者仍需配置并核对两侧地址。
刷新读取图 ID/schema 并更新 VID 向量索引，不写入图记录。

## License

Apache License 2.0
