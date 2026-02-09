# 任务恢复功能

## 概述

任务恢复功能允许用户在任务过期或执行器容器被清理后继续对话，同时保留完整的会话上下文。

## 问题背景

在 Wegent 中，任务使用 Docker 容器（执行器）来处理 AI 对话。这些容器有生命周期限制：

| 任务类型 | 过期时间 | 场景 |
|---------|---------|------|
| Chat | 2 小时 | 日常对话 |
| Code | 24 小时 | 代码开发 |

当容器过期被清理后，用户尝试继续对话会遇到两个问题：

1. **容器不存在** - 原执行器容器已被删除
2. **会话上下文丢失** - Claude SDK 的 session ID 保存在容器内，随容器一起丢失

## 解决方案概览

```mermaid
flowchart TB
    subgraph 问题["❌ 原有问题"]
        A[容器过期] --> B[容器被清理]
        B --> C[Session ID 丢失]
        C --> D[AI 失去对话记忆]
    end

    subgraph 方案["✅ 解决方案"]
        E[检测过期/已删除] --> F[提示用户恢复]
        F --> G[重置容器状态]
        G --> H[从数据库读取 Session ID]
        H --> I[新容器恢复会话]
    end

    问题 -.->|任务恢复功能| 方案
```

## 用户操作流程

```mermaid
sequenceDiagram
    actor 用户
    participant 前端
    participant 后端
    participant 新容器

    用户->>前端: 向过期任务发送消息
    前端->>后端: POST /tasks/{id}/append
    后端-->>前端: HTTP 409 TASK_EXPIRED_RESTORABLE
    前端->>用户: 显示恢复对话框

    alt 选择继续对话
        用户->>前端: 点击"继续对话"
        前端->>后端: POST /tasks/{id}/restore
        后端->>后端: 重置任务状态
        后端-->>前端: 恢复成功
        前端->>后端: 重发消息
        后端->>新容器: 创建容器 + 传递 Session ID
        新容器->>新容器: 使用 Session ID 恢复会话
        新容器-->>用户: AI 继续对话（保留上下文）
    else 选择新建对话
        用户->>前端: 点击"新建对话"
        前端->>后端: 创建新任务
    end
```

## 核心机制

### 1. 过期检测

后端在处理消息追加请求时，检查以下条件：

| 检查项 | 条件 | 结果 |
|-------|------|------|
| executor_deleted_at | 最后一个 ASSISTANT subtask 标记为 true | 返回 409 |
| 过期时间 | 超过配置的过期小时数 | 返回 409 |

### 2. 任务恢复 API

**端点**: `POST /api/v1/tasks/{task_id}/restore`

恢复操作执行以下步骤：

```mermaid
flowchart LR
    A[验证任务] --> B[重置 updated_at]
    B --> C[清除 executor_deleted_at]
    C --> D[清除 executor_name]
    D --> E[返回成功]
```

| 步骤 | 说明 |
|------|------|
| 清除 executor_deleted_at | 允许任务接收新消息 |
| 清除 executor_name | 强制创建新容器（不复用旧容器名） |

### 3. Claude Session ID 持久化

为了让新容器能恢复之前的会话上下文，Session ID 被持久化到数据库：

```mermaid
flowchart TB
    subgraph 保存流程["保存 Session ID"]
        direction LR
        A1[Claude SDK 返回 session_id] --> A2[写入 result 字典]
        A2 --> A3[Backend 提取保存到 DB]
        A2 --> A4[本地文件备份]
    end

    subgraph 读取流程["读取 Session ID"]
        direction LR
        B1[任务下发] --> B2{数据库有值?}
        B2 -->|是| B3[使用数据库值]
        B2 -->|否| B4{本地文件有值?}
        B4 -->|是| B5[使用本地文件值]
        B4 -->|否| B6[创建新会话]
    end

    保存流程 --> 读取流程
```

**存储策略**：

| 存储位置 | 用途 | 优先级 |
|---------|------|-------|
| 数据库 `subtasks.claude_session_id` | 主存储，支持跨容器恢复 | 高 |
| 本地文件 `.claude_session_id` | 备份，同容器内快速读取 | 低 |

## 数据流详解

### 任务下发时（Backend → Executor）

```mermaid
flowchart LR
    A[dispatch_tasks] --> B[查询 related_subtasks]
    B --> C{找到 ASSISTANT<br/>且有 session_id?}
    C -->|是| D[取最新的 session_id]
    C -->|否| E[session_id = null]
    D --> F{new_session?}
    E --> G[返回任务数据]
    F -->|是| H[清空 session_id]
    F -->|否| G
    H --> G
```

### 任务完成时（Executor → Backend）

```mermaid
flowchart LR
    A[Claude SDK<br/>返回 ResultMessage] --> B[提取 session_id]
    B --> C[添加到 result 字典]
    C --> D[report_progress]
    D --> E[Backend update_subtask]
    E --> F[保存到数据库]
```

## Pipeline 模式处理

在 Pipeline 模式下，当用户确认进入下一阶段时：

```mermaid
flowchart LR
    A[Stage 1 完成] --> B[用户确认]
    B --> C[new_session = true]
    C --> D[不传递旧 session_id]
    D --> E[Stage 2 创建新会话]
```

**原因**：每个 Pipeline 阶段可能使用不同的 Bot，需要独立的会话上下文。

## Session 过期处理

当 Claude SDK 返回 session 相关错误时，自动降级：

```mermaid
flowchart TB
    A[尝试恢复会话] --> B{连接成功?}
    B -->|是| C[继续使用恢复的会话]
    B -->|否| D{是 session 错误?}
    D -->|是| E[移除 resume 参数]
    E --> F[创建新会话]
    D -->|否| G[抛出异常]
```

**检测关键词**：`session`, `expired`, `invalid`, `resume`

## 配置

| 环境变量 | 说明 | 默认值 |
|---------|------|-------|
| `APPEND_CHAT_TASK_EXPIRE_HOURS` | Chat 任务过期小时数 | 2 |
| `APPEND_CODE_TASK_EXPIRE_HOURS` | Code 任务过期小时数 | 24 |

## 相关文件

### 后端

| 文件 | 职责 |
|------|------|
| `backend/app/api/endpoints/adapter/task_restore.py` | 恢复 API 端点 |
| `backend/app/services/adapters/task_restore.py` | 恢复服务逻辑 |
| `backend/app/services/adapters/executor_kinds.py` | Session ID 读取/保存，executor_deleted_at 标记 |
| `backend/app/services/adapters/task_kinds/operations.py` | 追加前过期检查 |
| `backend/alembic/versions/x4y5z6a7b8c9_*.py` | 数据库迁移 |

### Executor

| 文件 | 职责 |
|------|------|
| `executor/agents/claude_code/claude_code_agent.py` | Session ID 读取，过期处理 |
| `executor/agents/claude_code/response_processor.py` | Session ID 添加到结果 |

### 前端

| 文件 | 职责 |
|------|------|
| `frontend/src/features/tasks/components/chat/TaskRestoreDialog.tsx` | 恢复对话框 |
| `frontend/src/features/tasks/components/chat/useChatStreamHandlers.tsx` | 恢复流程处理 |
| `frontend/src/utils/errorParser.ts` | 解析 TASK_EXPIRED_RESTORABLE 错误 |

### Shared

| 文件 | 职责 |
|------|------|
| `shared/models/db/subtask.py` | Subtask 模型（含 claude_session_id 字段） |
