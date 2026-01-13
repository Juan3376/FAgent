# 功能需求与开发规范 (Feature Specifications & Guidelines)

> 本文档用于记录系统功能的详细需求、技术方案及多端协作任务分配。
> 新需求请按模板追加至文档末尾。

---

## 0. 🛡️ 标准协作分工规范 (Standard Collaboration Workflow)

面对一个新的功能需求时，各端角色的标准职责划分如下：

### 🟢 Backend (后端开发)
**核心职责**：数据持久化、业务逻辑、接口契约。
1.  **数据库设计 (DB Schema)**: 设计表结构、索引、迁移脚本 (Migration)。
2.  **接口定义 (API Contract)**: 确定 API 路径、Method、请求参数、响应结构（优先提供 Mock 数据或文档）。
3.  **业务逻辑 (Business Logic)**: 实现核心业务流程、权限校验、错误处理。
4.  **任务调度 (Scheduling)**: 处理异步任务、队列、定时作业（如触发 Agent 任务）。

### 🔵 Agents (智能体开发)
**核心职责**：LLM 交互、Prompt 工程、工具能力。
1.  **Prompt 工程**: 设计、测试和优化 System Prompt 及 User Prompt。
2.  **工具开发 (Tools)**: 封装外部 API 或内部服务供 LLM 调用（Function Calling）。
3.  **服务封装**: 将复杂的 LLM 交互流程封装为简洁的 Python 函数/类，供 Backend 调用。
4.  **模型评估**: 验证不同模型（如 GPT-4, Claude, Gemini）在该场景下的表现。

### 🟠 Frontend (前端开发)
**核心职责**：界面呈现、用户交互、状态管理。
1.  **UI/UX 实现**: 根据设计稿或需求描述还原界面，注重响应式和交互体验。
2.  **状态管理**: 设计合理的前端数据流（Store/Hooks），处理 Loading、Error 等状态。
3.  **接口对接**: 调用 Backend 提供的 API，处理数据格式转换。
4.  **Mock 开发**: 在后端接口未就绪时，基于接口契约优先开发 UI。

---

## 1. 📝 需求：自动会话总结 (Auto Conversation Summary)

### � 时间线
- **提出时间**: 2026-01-07
- **最后更新**: 2026-01-08

### 🎯 需求目标
用户完成一轮对话后，系统自动生成简短标题（如 "Python 排序算法"），替换默认的 "Conversation ID"。

### 🛠️ 任务分工表

| 角色 | 任务项 | 详细说明 | 状态 | 完成时间 |
| :--- | :--- | :--- | :--- | :--- |
| **Backend** | **DB 变更** | `conversations` 表新增 `title` 字段 (TEXT)。 | ✅ Done | 2026-01-08 |
| **Backend** | **接口升级** | `create_conversation` 支持传入 `title`；新增 `PATCH /conversation/{cid}` 接口。 | ✅ Done | 2026-01-08 |
| **Backend** | **触发机制** | 在 `chat_stream` 结束后，异步触发 Agent 的总结任务。 | ✅ Done | 2026-01-08 |
| **Agents** | **Prompt 设计** | 设计"总结助手" Prompt，要求输出 5-15 字以内的标题。 | ✅ Done | 2026-01-08 |
| **Agents** | **接口封装** | 提供 `POST /agent/summary/generate` 接口。 | ✅ Done | 2026-01-08 |
| **Frontend** | **UI 展示** | 侧边栏列表渲染 `title` 字段（若为空则显示默认 ID）。 | ✅ Done | 2026-01-07 |
| **Frontend** | **被动更新** | 监听或在下次刷新时获取最新标题。 | ✅ Done | 2026-01-07 |

---

## 2. 🗂️ 需求：智能侧边栏 (Smart Sidebar)

### � 时间线
- **提出时间**: 2026-01-08
- **最后更新**: 2026-01-08

### 🎯 需求目标
仿照 ChatGPT 体验，对历史会话进行时间分组（今天、昨天、7天内），并支持重命名和删除。

### 🛠️ 任务分工表

| 角色 | 任务项 | 详细说明 | 状态 | 完成时间 |
| :--- | :--- | :--- | :--- | :--- |
| **Backend** | **重命名接口** | 实现 `PATCH /api/chat/conversation/{cid}`，支持修改 `title`。 | ✅ Done | 2026-01-08 |
| **Backend** | **删除接口** | 确保 `DELETE /api/chat/conversation/{cid}` 可用。 | ✅ Done | 2026-01-07 |
| **Frontend** | **时间分组** | 实现 `Today`, `Yesterday`, `Previous 7 Days` 的分组算法。 | ✅ Done | 2026-01-08 |
| **Frontend** | **交互实现** | 增加“编辑”和“删除”按钮（Hover 显示）；实现确认弹窗。 | ⏳ Pending | - |
| **Frontend** | **状态同步** | 操作成功后，乐观更新 (Optimistic Update) 本地列表。 | ⏳ Pending | - |

---

son
  {
    "title": "New Title"
  }
  ```
- **Response**: `200 OK`

### Request Headers (推荐)
所有 API 请求建议携带以下 Header：
- `X-Request-ID`: 请求追踪 ID（可选，后端会自动生成）

> 注：`cid` 在 request body 中传递，无需在 Header 中重复
## 3. 🔗 需求：请求追踪系统 (Request Tracing)

### 📅 时间线
- **提出时间**: 2026-01-11
- **最后更新**: 2026-01-11

### 🎯 需求目标
实现全链路请求追踪，通过 `request_id` + `cid` 串联同一请求在 Backend、Agents 等服务中的所有日志，便于问题排查。

### 📐 技术方案

**追踪标识：**
- `request_id (rid)`: 唯一标识一次请求，格式为 UUID 前8位（如 `a1b2c3d4`）
- `cid`: 会话 ID，标识同一会话的所有请求

**传递方式：**
- `request_id`: 前端 → Backend → Agents，通过 HTTP Header `X-Request-ID` 传递
- `cid`: 在 request body 中传递（已有字段，无需额外处理）
- 如果前端未提供 `X-Request-ID`，Backend 自动生成

**日志格式：**
```
[rid=a1b2c3d4 cid=5] [REQ] POST /api/chat/send/stream
[rid=a1b2c3d4 cid=5] [ROUTER_INTENT] route=market | task=get_quote
[rid=a1b2c3d4 cid=5] [TOOL_CALL] market_service.get_quote
```

### 🛠️ 任务分工表

| 角色 | 任务项 | 详细说明 | 状态 | 完成时间 |
| :--- | :--- | :--- | :--- | :--- |
| **Backend** | **中间件** | 从 Header 获取或自动生成 `request_id`，存入上下文 | ✅ Done | 2026-01-11 |
| **Backend** | **日志前缀** | 所有日志自动添加 `[rid=xxx cid=yyy]` 前缀 | ✅ Done | 2026-01-11 |
| **Backend** | **Header 传递** | 调用 Agents 时传递 `X-Request-ID` Header | ✅ Done | 2026-01-11 |
| **Agents** | **中间件** | 从 Header 获取 `rid`，从 body 获取 `cid`，存入上下文 | ✅ Done | 2026-01-11 |
| **Agents** | **日志前缀** | Router/SubAgent 日志自动添加追踪前缀 | ✅ Done | 2026-01-11 |
| **Frontend** | **生成 rid** | 每次请求生成 UUID 作为 `request_id` | ✅ Done | 2026-01-11 |
| **Frontend** | **Header 设置** | 在 API 请求中添加 `X-Request-ID` Header | ✅ Done | 2026-01-11 |

### 📝 前端实现指南

```typescript
// 生成 request_id
const generateRequestId = () => crypto.randomUUID().slice(0, 8);

// API 请求示例
const sendMessage = async (cid: number, message: string) => {
  const requestId = generateRequestId();
  
  const response = await fetch('/api/chat/send/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Request-ID': requestId,  // cid 已在 body 中，无需 Header
    },
    body: JSON.stringify({ cid, user_message: message }),
  });
  
  // ...
};
```

---

## 4. � 需求：优化会话总结准确性 (Optimize Conversation Summary Accuracy)

### 📅 时间线
- **提出时间**: 2026-01-11
- **最后更新**: 2026-01-11

### 🎯 需求目标
解决当前自动生成的会话标题存在的问题，提升用户体验。
1.  **内容不准**：未能精准捕捉用户意图，经常生成与核心主题无关的标题。
2.  **废话较多**：包含“关于”、“讨论”、“咨询”等无意义词汇。
3.  **格式混乱**：包含引号、书名号、`Title:` 前缀等符号。

### 🛠️ 任务分工表

| 角色 | 任务项 | 详细说明 | 状态 | 完成时间 |
| :--- | :--- | :--- | :--- | :--- |
| **Agents** | **Prompt 优化** | 升级 System Prompt，增加“精准概括”、“拒绝废话”等强约束；提供 Few-Shot 示例（如 Input -> Output）。 | ✅ Done | 2026-01-11 |
| **Agents** | **后处理增强** | 增强 `_clean_title` 方法，增加对书名号、常见前缀（如 `summary:`）的清洗逻辑；严格控制长度（15字内）。 | ✅ Done | 2026-01-11 |
| **Backend** | **触发策略优化** | (可选) 优化消息截取逻辑（目前固定前6条），考虑根据 Token 数量截取；支持手动重新生成标题的接口。 | ⏳ Pending | - |

---

## 5. �🔌 接口契约草稿 (API Draft)

### Update Conversation Title
- **Endpoint**: `PATCH /api/chat/conversation/{cid}`
- **Body**:
  ```json
  {
    "title": "New Title"
  }
  ```
- **Response**: `200 OK`

---

## 6. 🧠 需求：动态模型切换 (Dynamic Model Switching)

### 📅 时间线
- **提出时间**: 2026-01-12
- **最后更新**: 2026-01-12

### 🎯 需求目标
支持用户在前端选择不同的 LLM 模型进行对话，后端需支持动态切换模型参数。

### 📝 模型映射表 (Model Mapping)

经过测试，以下模型可用：

| 前端显示名称 | 后端映射值 | 状态 |
| :--- | :--- | :--- |
| `mimo-v2-flash` | `xiaomi/mimo-v2-flash:free` | ✅ 可用 |
| `glm-4.5-air` | `z-ai/glm-4.5-air:free` | ✅ 可用 |
| ~~`qwen3-coder`~~ | ~~`qwen/qwen3-coder:free`~~ | ❌ 超时 |
| ~~`gpt-oss-120b`~~ | ~~`openai/gpt-oss-120b:free`~~ | ❌ 404 |

### 🛠️ 任务分工表

| 角色 | 任务项 | 详细说明 | 状态 | 完成时间 |
| :--- | :--- | :--- | :--- | :--- |
| **Backend** | **参数透传** | `ChatSendRequest` 增加 `model` 字段 (Optional[str])，透传给 Agents 服务。 | ✅ Done | 2026-01-14 |
| **Backend** | **模型配置接口** | 新增 `GET /api/chat/models` 接口，返回可用模型列表供前端动态获取。 | ✅ Done | 2026-01-14 |
| **Agents** | **模型适配** | `ChatAgent` 支持接收 `model` 参数，并动态调用对应 LLM。 | ✅ Done | 2026-01-14 |
| **Agents** | **模型列表接口** | 新增 `GET /agent/chat/models` 接口，返回可用模型配置。 | ✅ Done | 2026-01-14 |
| **Frontend** | **动态模型列表** | 从 `/api/chat/models` 获取模型列表，替代硬编码的下拉选项。 | ⏳ Pending | - |

### 🔧 详细技术要求 (Detailed Requirements)

#### Backend ✅
- **Endpoint**: `POST /api/chat/send` 和 `POST /api/chat/send/stream`
- **Request Body**: 增加可选字段 `model: str`
- **Logic**: 接收前端传来的 `model` 值，直接透传给 Agents 服务接口

- **新增 Endpoint**: `GET /api/chat/models`
- **Response**:
  ```json
  {
    "models": [
      {"id": "mimo-v2-flash", "name": "Mimo V2 Flash", "description": "小米极速模型，响应快速"},
      {"id": "glm-4.5-air", "name": "GLM 4.5 Air", "description": "智谱通用模型，能力均衡"}
    ],
    "default": "mimo-v2-flash"
  }
  ```

#### Agents ✅
- **Endpoint**: `POST /agent/chat/stream` 和 `POST /agent/chat/completion`
- **Request Body**: 增加可选字段 `model: str`
- **Logic**:
  1. 接收 `model` 参数
  2. 根据映射表将前端模型名转换为实际 Model ID
  3. 调用 `llm_service.chat_completion` 时传入 `model` 参数

- **新增 Endpoint**: `GET /agent/chat/models`
- **Response**: 同上

#### Frontend (⏳ 待实现)
- 应用启动时调用 `GET /api/chat/models` 获取模型列表
- 根据返回的 `models` 数组动态渲染下拉选项
- 使用返回的 `default` 作为默认选中值
- **好处**：当后端模型配置变更时，前端自动适配，无需修改代码

---

## 7. 👤 需求：用户认证系统 (User Authentication System)

### 📅 时间线
- **提出时间**: 2026-01-12
- **最后更新**: 2026-01-12

### 🎯 需求目标
在侧边栏底部实现用户注册和登录功能，支持多用户隔离，保障数据安全。
- 未登录状态：显示 "Login / Register" 按钮。
- 登录状态：显示用户头像、昵称，提供 "Logout" 选项。

### 🛠️ 任务分工表

| 角色 | 任务项 | 详细说明 | 状态 | 完成时间 |
| :--- | :--- | :--- | :--- | :--- |
| **Backend** | **数据库设计** | 新增 `users` 表，更新 `conversations` 表关联 `user_id`。 | ✅ Done | 2026-01-14 |
| **Backend** | **认证接口** | 实现注册（需支持邮箱）、登录（需支持邮箱/用户名）、获取用户信息接口；集成 JWT 认证。 | ✅ Done | 2026-01-14 |
| **Backend** | **数据隔离** | 升级现有 Chat 接口，强制校验 Token 并按 `user_id` 过滤数据。 | ✅ Done | 2026-01-14 |
| **Frontend** | **UI 组件** | 开发登录/注册模态框 (`AuthModal`)，改造 `UserProfile` 区域。 | ✅ Done | 2026-01-13 |
| **Frontend** | **状态管理** | 实现 `AuthContext`，管理 Token 持久化、请求拦截器 (Interceptor)。 | ✅ Done | 2026-01-13 |
| **Agents** | **上下文适配** | 支持接收 `user_id`，为未来个性化记忆 (Memory) 做准备。 | ⏳ Pending | - |

### 📐 技术方案详情

#### 1. Backend (后端)
- **Database Schema**:
  ```sql
  CREATE TABLE users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      email TEXT UNIQUE NOT NULL, -- 必填，用于找回密码及登录
      password_hash TEXT NOT NULL,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );
  -- conversations 表需新增 user_id 字段并建立外键
  ```
- **API Endpoints**:
  - `POST /api/auth/register`: 注册
    - Body: `{ "username": "string", "email": "string", "password": "string" }`
    - 校验: 邮箱格式、密码长度、用户名唯一性
  - `POST /api/auth/login`: 登录
    - Body: `{ "username": "string", "email": "string", "password": "string" }`
    - 说明: 登录时支持通过 `username` 或 `email` 字段进行认证
    - Return: `{ "access_token": "jwt_token", "user": { "id": 1, "username": "...", "email": "..." } }`
  - `GET /api/auth/me`: 获取当前用户信息 (Header: Authorization)
- **Middleware**:
  - 实现 JWT 认证中间件，拦截受保护路由。

#### 2. Frontend (前端)
- **UI Components**:
  - `UserProfile`: 根据登录状态切换显示内容。
  - `AuthModal`: 包含 "Sign In" 和 "Sign Up" 两个 Tab 的弹窗。
- **State Management**:
  - 使用 Context API + LocalStorage 存储 Token。
  - 封装 `fetch` 或 `axios`，自动在 Header 中添加 `Authorization: Bearer <token>`。

#### 3. Agents (智能体)
- **Context Injection**:
  - 后端在调用 Agents 接口时，需将 `user_id` 注入到 Request Context 中。
  - 示例日志：`[rid=xxx cid=yyy uid=101] [REQ] ...`


