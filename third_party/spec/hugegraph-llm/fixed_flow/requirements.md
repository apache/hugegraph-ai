## 需求列表

### 核心框架设计

**核心**：Scheduler类中的schedule_flow设计与实现

**验收标准**：
1.1. 核心框架尽可能复用资源，避免资源的重复分配和释放
1.2. 应该保证正常的请求处理指标要求
1.3. 应该能够配置框架整体使用的资源上限

### 固定工作流移植

**核心**：移植Web Demo中的所有用例
2.1. 保证使用核心框架移植后的工作流的程序行为和移植之前保持一致即可

**已完成的工作流类型**：
- build_vector_index: 向量索引构建工作流
- graph_extract: 图抽取工作流
- import_graph_data: 图数据导入工作流
- update_vid_embeddings: 向量更新工作流
- get_graph_index_info: 图索引信息获取工作流
- build_schema: 模式构建工作流
- prompt_generate: 提示词生成工作流
