# Ontogeny × hugegraph-ai 三步合并方案

> 状态：方案（未执行）
> 上游仓库：<https://github.com/apache/hugegraph-ai>（Apache-2.0，Python 3.10+）
> 主仓库：本仓库（ontogeny）
> 关联文档：[ARCHITECTURE.md](ARCHITECTURE.md) · [extensions.md](extensions.md) · [data-layer.md](data-layer.md)

---

## 0. 背景与总原则

### 0.1 为什么融合

hugegraph-ai 提供了 ontogeny 路线图上缺失的整块能力：

| hugegraph-ai 模块 | 能力 | 对 ontogeny 的意义 |
|---|---|---|
| `hugegraph-llm` | GraphRAG 问答、文本→知识图谱构建、NL→图查询 | 本体即知识图谱——补上"用自然语言问本体"与"从文档冷启动建模"两块 |
| `hugegraph-mcp` | HugeGraph 的 MCP 服务器（只读默认、写确认） | 工具 schema 设计参考（**不**单独挂载） |
| `hugegraph-ml` | 20+ 图算法：DeepWalk/Node2Vec 嵌入、节点分类、链接预测 | 填补 README 承诺但未实现的**语义搜索** |
| `hugegraph-python-client` | 全量 REST 客户端（同步） | 扩展内部按需引用 |
| `vermeer-python-client` | 图计算 SDK | 填补空壳端点 `POST /graph/algorithm` |

### 0.2 三条铁律（贯穿三步，任何一步不得违反）

1. **一个治理通道**——hugegraph-ai 的任何能力都不绕过 ontogeny 策略面：
   LLM 调用一律走 `sc.llm` 网关（预算 + 遥测），数据写入一律走 Action 五段式，
   对外工具一律挂本体 MCP 面受会话治理。不存在第二个入口。
2. **防腐层隔离**——ontogeny 不 fork、不重命名上游内部包。所有 import 耦合
   只允许出现在 `extensions/graph-*` 扩展内部；主包 `server/ontogeny/` 永远
   不出现 `hugegraph_llm` / `hugegraph_ml` 字样。
3. **图只出 ID，装配过引擎**——现有不变量"图投影返回 ID + 白名单属性，
   回引擎装配并施加 marking 掩码"是安全底线。GraphRAG 检索同样走它，
   绝不让 LLM 拿到裸 Gremlin 结果集或绕过掩码的原始行。

### 0.3 三步概览

| 步骤 | 名称 | 一句话 | 产出 | 预估 |
|---|---|---|---|---|
| 第一步 | 结构合并 | 上游原样进仓，零耦合零改动 | `third_party/hugegraph-ai/` + 工程豁免 + 溯源登记 | ~半天 |
| 第二步 | 功能初步合并 | `[graphai]` extra 接通 GraphRAG 问答与文本建图提案 | `extensions/graph-rag` + `ask_graph` 工具 + bootstrap 提案入环 | ~3–5 天 |
| 第三步 | 深度合并 | ML 语义搜索、图计算端点转正、RSI 与图的闭环 | `extensions/graph-ml`、`/graph/algorithm` 转正、新遥测信号 | ~1 周 |

依赖关系：每一步独立可交付、可回滚；第二步依赖第一步的树内结构；
第三步的 ML 部分依赖第二步的 extra 机制（复用同一模式）。

---

## 1. 第一步：结构合并（P0）

### 1.1 目标与边界

- **做什么**：hugegraph-ai 整棵树以 subtree 方式并入 ontogeny 仓库
  `third_party/hugegraph-ai/`，保留上游 git 历史；代码零改动、包名零重命名、
  依赖零接线。
- **不做什么**：不改上游任何文件（含 README/LICENSE）；`server/ontogeny/`
  不出现对 third_party 的任何 import；`pyproject.toml`/`uv.lock` 不新增依赖；
  CI 默认门不跑上游测试。
- **唯一验收标准**：合并后 ontogeny 全量验证与合并前基线完全一致
  （pytest 561 / ruff / tsc / vitest 245 / build / e2e 8），且两边零耦合。

### 1.2 目录布局

```
ontogeny/
├── server/ontogeny/           # 主项目（不动）
├── extensions/                # 主项目扩展（不动）
├── third_party/hugegraph-ai/  # ← 唯一新增：上游原样
│   ├── hugegraph-llm/
│   ├── hugegraph-mcp/
│   ├── hugegraph-ml/
│   ├── hugegraph-python-client/
│   ├── vermeer-python-client/
│   └── LICENSE / NOTICE / README …   # 上游 License 原样保留
├── THIRD_PARTY.md             # 新增：来源/版本/同步策略登记
└── NOTICE                     # 追加一行组件说明
```

选 `third_party/` 而非 `toolkit/` 或并入 `server/`：目录名本身宣告
"外部上游代码"，为 lint/CI/依赖豁免提供天然边界。**不重命名上游内部包**
（`hugegraph_llm` 等）——改名留到功能融合期按需进行，结构期改名只会制造
无意义 diff 并断掉后续同步上游的能力。

### 1.3 Git 策略：subtree 合并

| 方式 | 保留上游历史 | 后续同步 | 在树内 | 结论 |
|---|---|---|---|---|
| **subtree merge** | ✅ | `git pull -X subtree` 一条命令 | ✅ | **采用** |
| git submodule | 留在外部 | 需进子仓 | ❌ 指针 | 不符合"合并" |
| 快照拷贝 | ❌ | 手工重拷 | ✅ | 兜底 |

hugegraph-ai 迭代快（0.x），subtree 让"吃上游修复"变成低风险例行操作，
且合并提交完整记录了基于上游哪个版本。

**钉版原则**：合并点必须是上游 release tag（fetch 后取最新 tag），禁止用
main 裸头；版本登记进 `THIRD_PARTY.md`。

### 1.4 工程豁免（合并后立刻做）

| 工具 | 处理 | 原因 |
|---|---|---|
| ruff | `extend-exclude` 追加 `third_party` | 上游代码不接受本项目 lint 规则 |
| pytest | 不改（`testpaths=["tests"]` 已天然隔离） | 上游测试不进默认门 |
| uv | 零接线；验证 `uv.lock` 合并后无新包 | 嵌套 workspace：third_party 自带 `[workspace]`，根不认领其成员 |
| CI 默认门 | 不跑 third_party 测试 | 需 HG server/torch，重且脆 |
| CI 新增 | smoke job：上游 LICENSE 在位 + 目录存在 | 防误删 |
| .gitignore | 不排除 | 代码要在树内被跟踪 |

### 1.5 合规与溯源

- 双方均 Apache-2.0，无许可冲突；上游 LICENSE/NOTICE 随树保留；
- 仓库根 `NOTICE` 追加："本产品包含 Apache HugeGraph AI 组件
  (https://github.com/apache/hugegraph-ai)，© Apache Software Foundation"；
- `THIRD_PARTY.md` 登记：来源 URL、tag、合并日期、同步策略
  （"禁止直接修改 third_party 内代码；确需修改走 `third_party/patches/`
  目录并在登记表记录"）。

### 1.6 执行清单

```bash
# 1. 接上游、取 tag
git remote add hugegraph-ai https://github.com/apache/hugegraph-ai.git
git fetch hugegraph-ai --tags
UPSTREAM_TAG=<最新 release tag>

# 2. subtree 首次合并（保留上游作者）
git merge --allow-unrelated-histories -s ours --no-commit hugegraph-ai/$UPSTREAM_TAG
git read-tree --prefix=third_party/hugegraph-ai -u hugegraph-ai/$UPSTREAM_TAG
git commit   # 合并提交

# 后续同步上游（二期/三期需要新版本时）：
git pull -X subtree=third_party/hugegraph-ai hugegraph-ai <tag>
```

随后：ruff exclude、THIRD_PARTY.md、NOTICE 三处小改 → 验证 → 合并提交。

### 1.7 验收标准（全绿即过）

- [ ] `git grep -r "hugegraph_llm" server/ extensions/ tests/` 为零（零 import 耦合）
- [ ] `uv.lock` diff 为空（零依赖接线）
- [ ] `ruff check .` 全绿；`pytest` 561；tsc/vitest 245/build；e2e 8/8 —— 与基线一致
- [ ] `THIRD_PARTY.md`/`NOTICE` 就位；CI smoke job 绿

---

## 2. 第二步：功能初步合并（P1 GraphRAG 问答 + P2 文本建图）

### 2.1 目标

打通两条最有价值的能力，且**全部在 ontogeny 治理面内**：

- **GraphRAG 问答**：对本体图问自然语言（"哪些 HIGH 优先级订单延期了"），
  得到带对象引用的回答；
- **文本建图入环**：喂业务文档，产出建模提案（T1 人审 PR）与实体数据
  （受治理写入）。

### 2.2 依赖接线（第一次引用 third_party）

`pyproject.toml`：

```toml
[project.optional-dependencies]
graphai = [
  # path dependency 指向树内的上游子包（第一步结构合并的直接收益）
  "hugegraph-llm",
]
[tool.uv.sources]
hugegraph-llm = { path = "third_party/hugegraph-ai/hugegraph-llm", editable = false }
```

- extra 未安装 → 一切如常（`ask_graph` 工具不存在，assistant 保持现状）；
- CI 单独加一个 `graphai` job：装 extra 跑 graph-rag 的单测；无 HugeGraph
  服务时用 MockTransport，同 e2e 的自跳过模式。

### 2.3 LLM 网关桥（最大失控点的收口）

hugegraph-llm 自带 LLM 配置与调用栈。在扩展内实现适配类，把它的 LLM 接口
翻译到 `sc.llm`：

```
extensions/graph-rag/
├── extension.yaml        # kind: generic; provides: [capability:graph-rag]
│                         # requires: [capability:llm, capability:graph-store]
│                         # config: 无新增密钥——LLM 配置复用运行时配置
└── ontogeny_ext_graph_rag/
    ├── __init__.py       # register(provide graph-rag)
    ├── llm_bridge.py     # HugeLLMAdapter: 实现 hugegraph-llm 期望的
    │                     #   LLM 抽象，内部全部转调 sc.llm.chat()
    ├── retriever.py      # 检索：经 ontogeny 查询路径（掩码 + 装配）
    ├── tools.py          # ask_graph 工具注册进本体 MCP 目录
    └── extract.py        # P2：文本 → 建模提案 / 实体写入计划
```

约束：
- hugegraph-llm 自己的 settings/LLM 配置文件**一律不读**；
- 它发起的每次模型调用都经 `sc.llm` → 计入 agent/函数的预算与遥测体系；
- `ask_graph` 是**只读**工具：检索结果必须先经 `sc.query` 装配（marking
  生效），回答必须携带对象 ID 引用（可点击回溯）。

### 2.4 capability 契约（core 新增，唯一的主包改动）

`server/ontogeny/ext_host.py` 的能力表与降级矩阵扩展：

```
capability:graph-rag -> sc.graph_rag（GraphRAGService | None）
```

未安装 extra / 无图投影 / 无 LLM 时为 `None`，对外报告
`graphrag_blocked_by: "extra-not-installed" | "projection-not-wired" | "llm-not-configured"`
——沿用 `projection_blocked_by` 的降级原因码风格，前端据此渲染引导。

### 2.5 对外表面（全部走既有治理）

| 入口 | 治理 |
|---|---|
| MCP 工具 `ask_graph(query)`（只读） | 会话内、计 steps 预算、Cedar 对底层读生效 |
| Console 升级版 assistant（grounding 从静态 meta 升级为图检索） | 登录态（require_authenticated） |
| P2：`POST /bootstrap/from-docs`（传文档 → 建模提案） | **require_admin**；产物是 ProposalRow（T1），不是直接落库 |
| P2：抽取实体写回 | 走 Action（幂等键 + agent 场景审批门） |

### 2.6 文本建图入环（P2，与 RSI 宪法对齐）

hugegraph-llm 的 KG 构建输出（schema 候选 + 实体）映射进 ontogeny 的
既有治理结构，而不是另起管道：

1. 文档 → LLM 抽取（经 llm_bridge）→ schema 候选
   （ObjectType/LinkType/Action 草案）；
2. schema 候选 → 包装为 **ProposalRow（T1 awaiting_human）**，走
   promote 分支目录 + 人审——与 RSI 提案完全同一条宪法通道；
3. 实体实例 → 生成 Action 执行计划（`create-*` action，幂等键 =
   文档 hash + 实体名），agent 场景挂审批门；
4. 每个抽取步骤记遥测（模型、token、耗时）→ /admin/metrics 可见。

### 2.7 验收标准

- [ ] `pip install -e '.[graphai]'` 后，MCP 工具目录出现 `ask_graph`；
  未装 extra 时无此工具、控制台显示 `graphrag_blocked_by` 引导
- [ ] `ask_graph` 回答含对象 ID 引用；无 marking claim 的 principal 拿不到
  被掩码字段的值（有专项测试）
- [ ] LLM 调用全部出现在 ontogeny 遥测中；hugegraph-llm 不直连模型
  （代码评审点 + 运行时断言：llm_bridge 外无 LLM import）
- [ ] 文本建图产物是 T1 提案（人审），不存在直接写 schema 的路径
- [ ] 全量回归绿 + graphai job 绿

---

## 3. 第三步：深度合并（P3）

### 3.1 ML 语义搜索（hugegraph-ml）

- 新扩展 `extensions/graph-ml`，optional extra `[ml]`（torch 依赖重，
  独立隔离，缺失即降级）；
- **嵌入管线**：对投影在 HugeGraph 里的对象跑 DeepWalk/Node2Vec →
  向量写入对象表的向量属性（`vector(d)` 类型已存在，映射 JSON；向量检索
  优先 HugeGraph 自带能力，不足再评估 pgvector）；
- 对外表皮：`POST /objects/{type}/semantic-search`（只读、登录态、掩码生效）
  + MCP 工具 `search_similar`；
- 训练/重建任务是**管理面**操作（require_admin），跑在独立进程
  （复用函数沙箱的子进程模式，防 torch 卡事件循环）。

### 3.2 图计算端点转正（vermeer / HugeGraph OLAP）

- 现状：`POST /graph/algorithm` 是空壳（有投影时返回 200 null）；
- 新扩展 `extensions/graph-compute`，注册 `capability:graph-compute`；
- 实现 pagerank / 社区发现 / 最短路三类任务：提交异步任务 → 查询结果
  （ID 集）→ **回引擎装配**返回白名单属性；
- 结果可作为 evolve 的遥测信号（如 pagerank 异常节点 → 建议建模关注）。

### 3.3 RSI 与图的闭环（融合的复利所在）

新增两类遥测信号，让图 AI 的使用数据反哺自进化：

| 信号 | 来源 | 驱动的提案 |
|---|---|---|
| `graphrag-low-confidence` | ask_graph 检索得分低/无引用回答 | 建模缺口 → add-property / 新 LinkType 提案（T1） |
| `semantic-search-miss` | 语义搜索零结果查询 | 嵌入覆盖缺口 / 同义词属性提案 |

### 3.4 部署形态

- `compose.yaml` 新 profile `graphai`：ontogeny + HugeGraph Server +
  （可选）vermeer；extra 预装进镜像的多阶段构建层；
- 镜像分层：基础镜像不含 torch；`[ml]` 走独立 tag（`ontogeny:ml`）。

### 3.5 验收标准

- [ ] 语义搜索端到端可用（登录态、掩码、空结果给引导而非空数组）
- [ ] `/graph/algorithm` 转正：3 类算法 + 异步任务查询 + 引擎装配返回
- [ ] 两个新遥测信号出现在 Evolution 控制台并能驱动提案
- [ ] 默认镜像（无 extra）与 `[ml]` 镜像分别构建成功；降级矩阵测试绿

---

## 4. 明确不做的事（三步全程有效）

1. **不 fork / 不 vendor**——上游以 subtree 进仓，版本钉 tag，改动只经
   防腐层与 patches 目录；
2. **不挂第二个 MCP 服务器**——hugegraph-mcp 仅作库引用；
3. **不让 LLM 生成裸 Gremlin 执行**——翻译目标永远是 ontogeny 查询 DSL；
4. **不让 hugegraph-llm 直连 LLM**——一律经 `sc.llm` 网关桥；
5. **不把 torch 放进默认依赖**——`[ml]` 独立 extra；
6. **不重命名上游内部包**——改名仅在功能融合确需时逐个进行并登记。

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| 上游 0.x 迭代快、接口漂移 | subtree 钉 tag；防腐层（extensions/graph-rag）吸收变化；升级 = pull tag + 回归 |
| 依赖冲突（openai SDK、torch vs litellm） | extra 隔离 + 独立 CI job；graphai/ml 各自的锁文件策略在 P1 定型 |
| 同步客户端混入 async 路径 | pyhugegraph 仅在扩展内经 `asyncio.to_thread` 使用；投影主路径维持自研 async 适配器 |
| 治理旁路（raw Gremlin / 直连 LLM / 直接写 schema） | 三条铁律 + 专项测试（2.7 的断言）+ 代码评审 checklist |
| 仓库体积增长 | 上游仓库 <50MB，subtree 一次性带入历史，可接受；后续同步用 shallow tag pull |

## 6. 里程碑总表

| 里程碑 | 内容 | 验收核心 |
|---|---|---|
| **M0 结构合并** | third_party 进树 + 豁免 + 溯源 | 基线全绿、零耦合 |
| **M1 GraphRAG** | `[graphai]` + graph-rag 扩展 + ask_graph + 网关桥 | 掩码/引用/遥测三项治理测试绿 |
| **M2 建图入环** | 文档 → T1 提案 + 实体 Action 写回 | 不存在绕过提案的 schema 写入路径 |
| **M3 语义搜索** | `[ml]` + graph-ml 扩展 + 向量属性 | 降级矩阵绿、管理面隔离 |
| **M4 图计算 + 闭环** | vermeer/OLAP 转正 + 两个新遥测信号 | /graph/algorithm 转正、提案可驱动 |
