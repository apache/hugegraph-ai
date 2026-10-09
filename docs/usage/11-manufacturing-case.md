# 11 · 案例流程：离散制造运营闭环（domains/manufacturing-system · 数字来自真实执行捕获）

> 所属：[使用文档](../README.md#第二部分--使用文档part-ii--usage)

**中文** | [English](../en/usage/11-manufacturing-case.md)


15 对象 · 15 链接 · 12 动作 · 5 函数 · 6 策略 · 1 投影 · 2 评测套件 · 2 Agent 插件 + 自带种子（`seed/*.sql` 名词 + `demo-story.yaml` 动词）。启动时 --demo 自动重放的演示剧本即以下链路。

## 第一幕 · 接入与查询（seed → sync → query）

1. **本体加载**：serve --demo 一条命令完成播种/复制/构建/发布；快照可从 Git 随时重建
2. **数据接入**：15 类对象水位增量同步，首批 **57 行**；坏行进隔离区不阻塞
   （sample: bom +8 · customer +3 …）
3. **查询与安全**：派生属性实时计算（SO-2026-0001 距交付 ≈58 天）；`region` 带 commercial 标记 → 无授权身份看到 `__masked__`
   （without: `__masked__` · with markings: east）

▼ 业务执行（五段式动作）

## 第二幕 · 订单 → 排产 → 报工 → 质检 → 维修 → 采购（12 个动作的日常）

4. **确认订单**：dry-run 规则逐条 ✅ → 执行 `DRAFT→CONFIRMED`、版本 +1、修订落库
5. **越权被拒**：操作工确认订单 → `POLICY_DENIED`，**拒绝留痕**
6. **排产下达**：`create-object` + `newId()` → `PO-000001 RELEASED`；重复下达被规则拦
7. **工序报工**：合格数 3→5（表达式在事务内求值）；报废率派生 25%→16.67%
8. **质检登记**：FAIL 不填缺陷数 → 拒绝；补齐后执行并条件触发 QMS webhook
9. **维修闭环**：函数型动作服务端反查厂区 → 开单；开工/关闭 `modify-linked` 联动设备 `MAINTENANCE→RUNNING`；跨厂区关闭被行级策略拒；历史工单停机 **51.5h**（派生）
10. **采购**：buyer 制单不能审批，procurement_manager 审批——制单/审批分离直接写在 Cedar 里

▼ 计算 · 追溯 · 治理 · 进化

## 第三幕 · 函数 · 图 · 审计 · RSI · outbox（确定性内核 + 治理内进化）

11. **函数**：齐套检查（BOM 展开 vs 可用库存 → M-3002 缺 4）、设备 OEE、产能校验——沙箱只读，派生属性可见
    （shortage: M-3001 gap 1 · M-3002 gap 4 · M-3003 gap 2）
12. **多跳追溯**：M-3002 → BOM[B-02,B-05] → 产品[P-2001,P-2002]；explore 模式随机起点 DFS 展开 N 节点
13. **审计**：窗口内 12 条修订，执行/规则拒绝/策略拒绝三类齐全
14. **时间旅行**：更新=关旧版插新版；任意历史时刻可重建 → RSI 回放的数据底座
15. **RSI 闭环**：运维反复按未建模字段 workgroup 过滤 → 信号 → 提案 → **双套件全绿** → T0 自动合并（预算 1/8）→ 新属性热加载生效
16. **outbox 投递**：webhook / projection / derivation / sse 四消费者各自游标推进，互不拖累
