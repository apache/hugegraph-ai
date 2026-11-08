## 2. 创建功能设计文档

### 上下文与触发条件 (Context & Trigger)

当实现边界、备选方案或兼容性仍需澄清时使用本阶段。需求可来自 issue、现有设计、用户指令或需求文档；不要求为已回答的问题额外创建或批准 `requirements.md`。

### 工作方式

1. 先检查现有实现、调用方、约束和测试，确认可复用的能力。
2. 记录必要的边界、备选方案、权衡、风险和验证方法；外部资料应注明来源。可用 `.workflow/{feature_name}/design.md` 作为本地工作文件。
3. 只有信息缺失会实质影响结果、存在关键取舍或用户明确要求审批时，才请求用户决定或批准。协作或长期保留的决策应写入受版本管理的文档或 issue；`.workflow/` 不随提交共享。

### `design.md` 文档规格与内容要求

设计文档可参考以下结构，按变更范围选择相关部分，并说明关键决策及其理由。

- **文件结构**: 一份 Markdown 文件；从下方示例中选择与变更相关的部分。
- **图表示例**: 在适当的情况下，使用 Mermaid.js 语法嵌入图表。

#### 示例格式应用

````markdown
# 设计文档: “记住我”功能

## 1. 概述 (Overview)

### 1.1. 目标 (Goals)

为用户提供“记住我”选项，允许其在关闭浏览器后的一段时间内（例如 30 天）保持登录状态，以提升回访用户的体验。

### 1.2. 范围 (Scope)

- **In-Scope**:
  - 在登录页面提供“记住我”复选框。
  - 用户勾选后，生成长效持久化令牌。
  - 用户下次访问时，通过令牌自动完成登录。
- **Out-of-Scope**:
  - 管理已登录设备或吊销特定令牌的功能。
  - 跨设备同步“记住我”状态。

### 1.3. 关联需求 (Related Requirements)

- (关联需求: F-Auth-05, NF-SEC-02)

## 2. 整体架构 (System Architecture)

### 2.1. 架构图 (Diagram)

[此处应嵌入一个高层级的架构图，用于清晰地展示新功能将如何融入现有系统，以及关键组件间的交互关系。**推荐使用序列图 (Sequence Diagram) 来描述交互流程，或使用组件图 (Component Diagram) / C4 模型来展示系统结构。**]

### 2.2. 设计决策与权衡 (Design Decisions & Trade-offs)

- **决策**: 采用独立的持久化令牌，而非延长会话(session)有效期。
  - **理由**: 增强安全性。长效会话更容易被劫持，而持久化令牌可以设计为一次性使用或与特定设备/IP 绑定，且不直接暴露会话 ID。
  - **权衡**: 实现逻辑比简单延长会话略复杂，需要额外的数据表和验证逻辑。

## 3. 数据模型 (Data Model)

**决策**: 新建`persistent_tokens`表来存储令牌信息，以实现关注点分离。

[如果需要修改数据库，应在此处描述表结构变更。**推荐使用实体关系图 (ER Diagram) 来清晰地展示数据模型。**]

## 4. API 接口设计 (API Design)

[对于每个新增或修改的 API 端点，都应提供详细的定义。]

### `[HTTP 方法] /api/path/to/endpoint`

- **描述**: [清晰地描述此端点的功能和用途。]
- **请求体 (Request Body)**:
  ```json
  {
    "key": "value_type",
    "another_key": "another_value_type"
  }
  ```
````

- **成功响应 (Success Response)**:
  - **状态码**: `200 OK`
  - **响应头 (Headers)**: [可选。列出关键的响应头，如 `Set-Cookie`。]
  - **响应体 (Body)**:
    ```json
    {
      "status": "success",
      "data": {}
    }
    ```
- **失败响应 (Error Response)**:
  - **状态码**: `4xx/5xx`
  - **响应体 (Body)**:
    ```json
    {
      "error": "A descriptive error message."
    }
    ```

## 5. 核心逻辑实现 (Core Logic)

- **令牌验证中间件 `verify_persistent_token`**:
  1. 在常规会话验证失败后触发。
  2. 从请求的`Cookie`中提取`remember_token`。
  3. 如果令牌不存在，则流程结束。
  4. 使用`SHA-256`对令牌进行哈希计算。
  5. 在`persistent_tokens`表中查找该哈希值。
  6. 若找到且`expires_at`未过期，则为该`user_id`创建一个新的会话(session)，并删除当前使用的持久化令牌（增强安全性，每次都换新令牌）。
  7. 若未找到或已过期，则清除客户端的无效`remember_token` Cookie。

## 6. 非功能性需求 (Non-Functional Requirements)

- **安全性 (Security)**:
  - 令牌在数据库中必须使用强哈希算法（如 SHA-256）存储，绝不能明文存储。
  - `remember_token` Cookie 必须设置为`HttpOnly`以防止 XSS 攻击，设置为`Secure`以确保只在 HTTPS 下传输。
- **性能 (Performance)**:
  - 令牌验证的数据库查询（基于主键）必须在`50ms`内完成。

## 7. 测试策略 (Testing Strategy)

- **单元测试**:
  - `generate_secure_token()`函数的随机性和唯一性。
  - `hash_token()`函数的正确性。
- **集成测试**:
  - `POST /api/auth/login`接口在`rememberMe`为 true/false 时，响应头的`Set-Cookie`是否正确。
  - `verify_persistent_token`中间件能否在有/无/无效/过期令牌的情况下正确处理。
- **端到端测试**:
  - 模拟用户勾选“记住我”并登录，关闭浏览器，30 分钟后再打开，应能自动登录。
  - 模拟令牌过期后，用户需要重新手动登录。

## 8. 风险与缓解措施 (Risks & Mitigation)

- **风险**: 用户的物理设备被盗，导致账户被非授权访问。

  - **缓解措施**: 在用户修改密码或手动“登出所有设备”时，必须清空该用户在`persistent_tokens`表中的所有记录。

- ⚠️ 若在设计过程中发现需求存在缺口，模型应主动建议返回功能需求澄清阶段
