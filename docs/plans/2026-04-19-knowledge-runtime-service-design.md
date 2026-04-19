---
sidebar_position: 1
---

# Knowledge Runtime 服务详细设计文档

> **版本**: v1.0
> **日期**: 2026-04-19
> **状态**: 设计评审中

## 一、概述

### 1.1 目标

创建独立的 `knowledge_runtime` 服务，作为 RAG 数据面的远程执行引擎，实现：

1. Backend 与重型 RAG 依赖（llama-index、pymilvus 等）的解耦
2. 支持灰度切换（local/remote 模式）
3. 保持现有 API 契约不变，对 Frontend/Chat Shell 透明

### 1.2 范围

**包含**：
- `knowledge_runtime` 服务实现
- Docker Compose 部署配置
- 服务间通信协议
- 健康检查与优雅关闭机制

**不包含**：
- Kubernetes 部署配置（后续迭代）
- 权限管理（由 Backend 控制）
- 直接访问 Backend 数据库
- `direct_injection` 和 `restricted_mediation` 逻辑（保留在 Backend）

### 1.3 设计决策摘要

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 部署方式 | Docker Compose 优先 | 先完成基础部署，后续扩展 K8s |
| 内容获取 | Backend 流式转发 | 适合小规模部署，无需额外存储配置 |
| 服务认证 | 共享 Token | 简单可靠，符合内部服务通信模式 |
| 错误处理 | 仅返回错误 | 保持语义清晰，调用方决定重试策略 |
| 服务端口 | 8200 | 与其他内部服务端口模式一致 |
| 健康检查 | 参考 Backend | 存活 + 就绪分离，优雅关闭支持 |

---

## 二、架构设计

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Backend (Control Plane)                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                   │
│  │  HTTP API    │  │  MCP Tools   │  │  Internal API│                   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                   │
│         │                  │                  │                         │
│         └──────────────────┼──────────────────┘                         │
│                            ▼                                            │
│                   ┌─────────────────┐                                   │
│                   │  Orchestrator   │                                   │
│                   │  (权限/元数据)   │                                   │
│                   └────────┬────────┘                                   │
│                            ▼                                            │
│                   ┌─────────────────┐                                   │
│                   │  Gateway Factory│                                   │
│                   │  (local/remote) │                                   │
│                   └────────┬────────┘                                   │
│                            │                                            │
│         ┌──────────────────┼──────────────────┐                         │
│         ▼                  ▼                  ▼                         │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐                    │
│  │LocalGateway │   │RemoteGateway│   │Content Ref  │                    │
│  │             │   │             │   │Builder      │                    │
│  └──────┬──────┘   └──────┬──────┘   └─────────────┘                    │
│         │                  │                                           │
└─────────┼──────────────────┼───────────────────────────────────────────┘
          │                  │ HTTP (Bearer Token)
          │                  ▼
          │     ┌─────────────────────────────────────────────────────────┐
          │     │                    knowledge_runtime                     │
          │     │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
          │     │  │  HTTP API    │  │  Content     │  │  Auth        │   │
          │     │  │  (FastAPI)   │  │  Fetcher     │  │  Middleware  │   │
          │     │  └──────┬───────┘  └──────┬───────┘  └──────────────┘   │
          │     │         │                  │                             │
          │     │         └──────────────────┼─────────────────────────────┤
          │     │                            ▼                             │
          │     │                   ┌─────────────────┐                    │
          │     │                   │  knowledge_engine│                    │
          │     │                   │  (执行内核)      │                    │
          │     │                   └────────┬────────┘                    │
          │     │                            ▼                             │
          │     │                   ┌─────────────────┐                    │
          │     │                   │  Milvus/ES/     │                    │
          │     │                   │  Qdrant         │                    │
          │     │                   └─────────────────┘                    │
          │     └─────────────────────────────────────────────────────────┘
          │
          ▼
   (local mode: 直接调用 knowledge_engine)
```

### 2.2 数据流图

#### 2.2.1 索引流程 (Index)

```
┌────────┐     ┌─────────┐     ┌───────────────────┐     ┌─────────────────┐
│ Front  │────▶│ Backend │────▶│ RemoteRagGateway  │────▶│knowledge_runtime│
└────────┘     └────┬────┘     └───────────────────┘     └────────┬────────┘
                    │                                              │
                    │ 1. 权限校验                                   │
                    │ 2. 解析 CRD 配置                              │
                    │ 3. 构建 ContentRef                            │
                    │ 4. 构建 RemoteIndexRequest                    │
                    │                                              │
                    │                                         5. 验证 Token
                    │                                         6. 获取内容
                    │◀─────────────────────────────────────────────┤
                    │         (content_ref.url)                    │
                    │                                              │
                    │                                         7. 调用 knowledge_engine
                    │                                         8. 返回结果
                    │◀─────────────────────────────────────────────┤
                    │                                              │
                    │ 9. 更新元数据状态                              │
                    ▼
```

#### 2.2.2 检索流程 (Query)

```
┌────────┐     ┌─────────┐     ┌───────────────────┐     ┌─────────────────┐
│Chat    │────▶│ Backend │────▶│ RemoteRagGateway  │────▶│knowledge_runtime│
│Shell   │     └────┬────┘     └───────────────────┘     └────────┬────────┘
                    │                                              │
                    │ 1. 解析 KB 配置                               │
                    │ 2. 构建 RemoteQueryRequest                    │
                    │    (包含每个 KB 的 runtime config)             │
                    │                                              │
                    │                                         3. 验证 Token
                    │                                         4. 调用 knowledge_engine
                    │                                         5. 返回 RemoteQueryResponse
                    │◀─────────────────────────────────────────────┤
                    │                                              │
                    ▼
```

### 2.3 组件职责

| 组件 | 职责 | 不承担的职责 |
|------|------|-------------|
| **Backend** | 权限校验、请求路由、结果组装、direct injection 决策、restricted mediation、元数据管理、状态回写 | 不执行实际的索引/检索操作（remote 模式） |
| **knowledge_runtime** | 协议转换、内容拉取、调用 knowledge_engine、返回结果序列化 | 不处理权限、不访问 Backend DB、不做路由决策 |
| **knowledge_engine** | 文档解析、分块、embedding、向量索引读写 | 不理解业务语义、不处理 HTTP 协议 |

---

## 三、服务接口设计

### 3.1 HTTP API 端点

#### 3.1.1 内部 RAG 接口

| 端点 | 方法 | 描述 |
|------|------|------|
| `/internal/rag/index` | POST | 索引文档 |
| `/internal/rag/query` | POST | 检索知识库 |
| `/internal/rag/delete-document-index` | POST | 删除文档索引 |
| `/internal/rag/purge-knowledge-index` | POST | 清空知识库索引 |
| `/internal/rag/drop-knowledge-index` | POST | 删除知识库索引结构 |
| `/internal/rag/all-chunks` | POST | 获取所有分块 |
| `/internal/rag/test-connection` | POST | 测试存储连接 |

#### 3.1.2 健康检查接口

| 端点 | 方法 | 描述 |
|------|------|------|
| `/health` | GET | 存活检查 (Liveness) |
| `/ready` | GET | 就绪检查 (Readiness) |
| `/startup` | GET | 启动完成检查 |
| `/shutdown/initiate` | POST | 触发优雅关闭 |
| `/shutdown/wait` | POST | 等待流完成 |
| `/shutdown/status` | GET | 关闭状态 |
| `/shutdown/reset` | POST | 重置关闭状态（测试用） |

### 3.2 请求/响应模型

#### 3.2.1 索引请求 (RemoteIndexRequest)

```python
class RemoteIndexRequest(KnowledgeRuntimeProtocolModel):
    knowledge_base_id: int
    document_id: int | None
    index_owner_user_id: int
    retriever_config: RuntimeRetrieverConfig
    embedding_model_config: RuntimeEmbeddingModelConfig
    splitter_config: NormalizedSplitterConfig
    source_file: str | None
    file_extension: str | None
    index_families: list[str] = ["chunk_vector"]
    content_ref: ContentRef  # 内容引用
    trace_context: dict[str, Any] | None
    user_name: str | None
    extensions: dict[str, Any] | None
```

#### 3.2.2 检索请求 (RemoteQueryRequest)

```python
class RemoteQueryRequest(KnowledgeRuntimeProtocolModel):
    knowledge_base_ids: list[int]
    query: str
    max_results: int = 5
    document_ids: list[int] | None
    metadata_condition: dict[str, Any] | None
    user_name: str | None
    knowledge_base_configs: list[RemoteKnowledgeBaseQueryConfig]
    enabled_index_families: list[str] = ["chunk_vector"]
    retrieval_policy: RetrievalPolicy = "chunk_only"
    extensions: dict[str, Any] | None
```

#### 3.2.3 检索响应 (RemoteQueryResponse)

```python
class RemoteQueryResponse(KnowledgeRuntimeProtocolModel):
    records: list[RemoteQueryRecord]
    total: int
    total_estimated_tokens: int = 0
```

#### 3.2.4 错误响应 (RemoteRagError)

```python
class RemoteRagError(KnowledgeRuntimeProtocolModel):
    code: str           # 错误码
    message: str        # 错误消息
    retryable: bool     # 是否可重试
    details: dict[str, Any] | None  # 详细信息
```

### 3.3 内容引用协议

`ContentRef` 是 discriminated union，支持两种模式：

#### 3.3.1 Backend 流式转发 (BackendAttachmentStreamContentRef)

```python
class BackendAttachmentStreamContentRef(KnowledgeRuntimeProtocolModel):
    kind: Literal["backend_attachment_stream"]
    url: str              # Backend 内部 URL
    auth_token: str       # 短期访问令牌
    expires_at: datetime | None
```

**流程**：
1. Backend 生成短期 JWT token (5分钟有效期)
2. `knowledge_runtime` 使用该 token 调用 Backend 获取内容
3. Backend 验证 token 后返回文件流

#### 3.3.2 预签名 URL (PresignedUrlContentRef)

```python
class PresignedUrlContentRef(KnowledgeRuntimeProtocolModel):
    kind: Literal["presigned_url"]
    url: str              # S3/MinIO 预签名 URL
    expires_at: datetime | None
```

**流程**：
1. Backend 生成 S3/MinIO 预签名 URL
2. `knowledge_runtime` 直接从对象存储获取内容

### 3.4 认证机制

采用 **共享 Token** 方式：

```
Backend → knowledge_runtime:
  Authorization: Bearer {INTERNAL_SERVICE_TOKEN}

knowledge_runtime → Backend (获取内容):
  Authorization: Bearer {content_ref.auth_token}
```

**配置项**：
- `INTERNAL_SERVICE_TOKEN`: 环境变量配置的共享密钥
- Token 验证：中间件检查 Authorization header

---

## 四、服务实现设计

### 4.1 目录结构

```
knowledge_runtime/
├── pyproject.toml              # 项目配置
├── knowledge_runtime/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 入口
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py           # 配置管理
│   │   ├── shutdown.py         # 优雅关闭管理
│   │   └── exceptions.py       # 异常定义
│   ├── api/
│   │   ├── __init__.py
│   │   ├── router.py           # API 路由
│   │   └── internal/
│   │       ├── __init__.py
│   │       └── rag.py          # RAG 内部接口
│   ├── services/
│   │   ├── __init__.py
│   │   ├── handlers.py         # 请求处理器
│   │   ├── content_fetcher.py  # 内容获取
│   │   └── embedding_factory.py # Embedding 模型工厂
│   └── middleware/
│       ├── __init__.py
│       └── auth.py             # 认证中间件
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_handlers.py
    ├── test_content_fetcher.py
    └── test_api/
        └── test_internal_rag.py
```

### 4.2 核心模块设计

#### 4.2.1 配置管理 (core/config.py)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Service
    HOST: str = "0.0.0.0"
    PORT: int = 8200
    DEBUG: bool = False

    # Auth
    INTERNAL_SERVICE_TOKEN: str = ""

    # Backend
    BACKEND_INTERNAL_URL: str = "http://backend:8000"

    # Graceful Shutdown
    GRACEFUL_SHUTDOWN_TIMEOUT: int = 30

    # OpenTelemetry
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "wegent-knowledge-runtime"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
```

#### 4.2.2 认证中间件 (middleware/auth.py)

```python
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from knowledge_runtime.core.config import settings

class InternalAuthMiddleware(BaseHTTPMiddleware):
    """Validate internal service token for protected endpoints."""

    PUBLIC_PATHS = {
        "/health",
        "/ready",
        "/startup",
        "/shutdown/initiate",
        "/shutdown/wait",
        "/shutdown/status",
        "/shutdown/reset",
    }

    async def dispatch(self, request: Request, call_next):
        # Skip auth for public paths
        if request.url.path in self.PUBLIC_PATHS:
            return await call_next(request)

        # Validate Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(status_code=401, detail="Missing authorization")

        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid authorization format")

        token = auth_header[7:]
        if token != settings.INTERNAL_SERVICE_TOKEN:
            raise HTTPException(status_code=403, detail="Invalid token")

        return await call_next(request)
```

#### 4.2.3 内容获取器 (services/content_fetcher.py)

```python
import httpx
from shared.models import (
    BackendAttachmentStreamContentRef,
    PresignedUrlContentRef,
    ContentRef,
)

class ContentFetcher:
    """Fetch document content from Backend or object storage."""

    async def fetch(self, content_ref: ContentRef) -> bytes:
        if content_ref.kind == "backend_attachment_stream":
            return await self._fetch_from_backend(content_ref)
        elif content_ref.kind == "presigned_url":
            return await self._fetch_from_presigned_url(content_ref)
        else:
            raise ValueError(f"Unknown content_ref kind: {content_ref.kind}")

    async def _fetch_from_backend(
        self,
        ref: BackendAttachmentStreamContentRef,
    ) -> bytes:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                ref.url,
                headers={"Authorization": f"Bearer {ref.auth_token}"},
                follow_redirects=True,
            )
            response.raise_for_status()
            return response.content

    async def _fetch_from_presigned_url(
        self,
        ref: PresignedUrlContentRef,
    ) -> bytes:
        async with httpx.AsyncClient() as client:
            response = await client.get(ref.url, follow_redirects=True)
            response.raise_for_status()
            return response.content
```

#### 4.2.4 请求处理器 (services/handlers.py)

```python
from knowledge_engine.services import DocumentService
from knowledge_engine.storage.factory import create_storage_backend_from_runtime_config
from knowledge_engine.embedding.factory import create_embedding_model_from_runtime_config
from shared.models import (
    RemoteIndexRequest,
    RemoteQueryRequest,
    RemoteQueryResponse,
    RemoteRagError,
)
from knowledge_runtime.services.content_fetcher import ContentFetcher
from knowledge_runtime.services.embedding_factory import EmbeddingModelFactory

class RagHandler:
    """Handle RAG operations by delegating to knowledge_engine."""

    def __init__(self):
        self._content_fetcher = ContentFetcher()
        self._embedding_factory = EmbeddingModelFactory()

    async def index_document(self, request: RemoteIndexRequest) -> dict:
        """Index a document using knowledge_engine."""
        # 1. Fetch content
        binary_data = await self._content_fetcher.fetch(request.content_ref)

        # 2. Build storage backend
        storage_backend = create_storage_backend_from_runtime_config(
            request.retriever_config
        )

        # 3. Build embedding model
        embed_model = await self._embedding_factory.create(
            request.embedding_model_config
        )

        # 4. Execute indexing
        service = DocumentService(storage_backend=storage_backend)
        return await service.index_document_from_binary(
            knowledge_id=str(request.knowledge_base_id),
            binary_data=binary_data,
            source_file=request.source_file or "unknown",
            file_extension=request.file_extension or "",
            embed_model=embed_model,
            user_id=request.index_owner_user_id,
            splitter_config=request.splitter_config.model_dump(exclude_none=True),
            document_id=request.document_id,
        )

    async def query(self, request: RemoteQueryRequest) -> RemoteQueryResponse:
        """Query knowledge bases using knowledge_engine."""
        # Implementation uses knowledge_engine query executor
        # ...
```

#### 4.2.5 优雅关闭管理 (core/shutdown.py)

```python
import asyncio
import time
from typing import Set, Optional

class ShutdownManager:
    """Manage graceful shutdown for knowledge_runtime."""

    def __init__(self):
        self._shutting_down: bool = False
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._active_streams: Set[int] = set()
        self._lock: asyncio.Lock = asyncio.Lock()
        self._shutdown_start_time: Optional[float] = None

    @property
    def is_shutting_down(self) -> bool:
        return self._shutting_down

    @property
    def shutdown_duration(self) -> float:
        if self._shutdown_start_time is None:
            return 0.0
        return time.time() - self._shutdown_start_time

    def get_active_stream_count(self) -> int:
        return len(self._active_streams)

    async def initiate_shutdown(self) -> None:
        async with self._lock:
            if self._shutting_down:
                return
            self._shutting_down = True
            self._shutdown_start_time = time.time()

    async def wait_for_streams(self, timeout: float = 30.0) -> bool:
        if len(self._active_streams) == 0:
            return True
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def reset(self) -> None:
        self._shutting_down = False
        self._shutdown_event.clear()
        self._active_streams.clear()
        self._shutdown_start_time = None

# Global instance
shutdown_manager = ShutdownManager()
```

### 4.3 依赖关系

```toml
# knowledge_runtime/pyproject.toml
[project]
name = "wegent-knowledge-runtime"
version = "1.0.0"
requires-python = ">=3.10,<=3.13"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
    "pydantic>=2.5.3",
    "pydantic-settings>=2.0.0",
    "httpx>=0.26.0",
    "wegent-shared",
    "wegent-knowledge-engine",
]

[tool.uv.sources]
wegent-shared = { path = "../shared", editable = true }
wegent-knowledge-engine = { path = "../knowledge_engine", editable = true }
```

---

## 五、部署设计

### 5.1 Docker Compose 配置

```yaml
# docker-compose.yml 新增服务
services:
  knowledge_runtime:
    image: ghcr.io/wecode-ai/wegent-knowledge-runtime:latest
    pull_policy: ${DOCKER_PULL_POLICY:-always}
    container_name: wegent-knowledge-runtime
    restart: always
    ports:
      - "${KNOWLEDGE_RUNTIME_PORT:-8200}:8200"
    environment:
      - HOST=0.0.0.0
      - PORT=8200
      - INTERNAL_SERVICE_TOKEN=${INTERNAL_SERVICE_TOKEN:-}
      - BACKEND_INTERNAL_URL=http://backend:8000
      - GRACEFUL_SHUTDOWN_TIMEOUT=${GRACEFUL_SHUTDOWN_TIMEOUT:-30}
      # OpenTelemetry Configuration
      # - OTEL_ENABLED=true
      # - OTEL_SERVICE_NAME=wegent-knowledge-runtime
      # - OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
    depends_on:
      - backend
    networks:
      - wegent-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8200/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
```

### 5.2 Backend 环境变量更新

```yaml
# docker-compose.yml backend 服务新增环境变量
services:
  backend:
    environment:
      # ... existing ...
      - KNOWLEDGE_RUNTIME_URL=${KNOWLEDGE_RUNTIME_URL:-http://knowledge_runtime:8200}
      - RAG_RUNTIME_MODE=${RAG_RUNTIME_MODE:-local}
      - INTERNAL_SERVICE_TOKEN=${INTERNAL_SERVICE_TOKEN:-}
```

### 5.3 Dockerfile

```dockerfile
# docker/knowledge_runtime/Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy package files
COPY shared/ /app/shared/
COPY knowledge_engine/ /app/knowledge_engine/
COPY knowledge_runtime/ /app/knowledge_runtime/

# Install dependencies
RUN uv pip install --system \
    -e /app/shared \
    -e /app/knowledge_engine \
    -e /app/knowledge_runtime

# Expose port
EXPOSE 8200

# Run service
CMD ["uvicorn", "knowledge_runtime.main:app", "--host", "0.0.0.0", "--port", "8200"]
```

---

## 六、Backend 集成变更

### 6.1 RemoteRagGateway 更新

无需修改，现有实现已支持完整协议：

```python
# backend/app/services/rag/remote_gateway.py
# 现有实现已覆盖所有操作
```

### 6.2 Gateway Factory 更新

无需修改，现有实现已支持模式切换：

```python
# backend/app/services/rag/gateway_factory.py
def _build_gateway(mode: str) -> RagGateway:
    if mode == "remote":
        return RemoteRagGateway()
    return LocalRagGateway()
```

### 6.3 配置验证

确保 Backend 配置正确：

```python
# backend/app/core/config.py
KNOWLEDGE_RUNTIME_URL: str = "http://localhost:8200"
RAG_RUNTIME_MODE: str | dict[str, str] = "local"

def get_rag_runtime_mode(self, operation: str) -> str:
    # 支持: "local", "remote", {"default": "local", "query": "remote"}
    ...
```

---

## 七、测试策略

### 7.1 单元测试

| 测试目标 | 测试内容 |
|----------|----------|
| `ContentFetcher` | Backend 流式获取、预签名 URL 获取、错误处理 |
| `RagHandler` | 请求解析、knowledge_engine 调用、响应组装 |
| `InternalAuthMiddleware` | Token 验证、公开路径跳过 |

### 7.2 集成测试

| 测试场景 | 验证内容 |
|----------|----------|
| 索引 → 检索 → 删除 | 完整生命周期 |
| 多知识库检索 | 配置正确传递 |
| 错误响应 | RemoteRagError 格式 |

### 7.3 端到端测试

```
Backend (remote mode) → knowledge_runtime → knowledge_engine → Mock Storage
```

验证：
- 请求/响应格式兼容
- 认证流程正确
- 错误正确传播

---

## 八、灰度发布策略

### 8.1 阶段一：服务部署

1. 部署 `knowledge_runtime` 服务
2. 保持 `RAG_RUNTIME_MODE=local`
3. 验证服务健康检查

### 8.2 阶段二：索引灰度

1. 设置 `RAG_RUNTIME_MODE={"default": "local", "index": "remote"}`
2. 验证索引操作正确执行
3. 监控错误率

### 8.3 阶段三：检索灰度

1. 设置 `RAG_RUNTIME_MODE={"default": "local", "query": "remote"}`
2. 验证检索结果与本地一致
3. 性能对比

### 8.4 阶段四：完全切换

1. 设置 `RAG_RUNTIME_MODE=remote`
2. 监控稳定性
3. 保留本地回退能力

### 8.5 阶段五：依赖清理

1. 从 Backend 移除重型 RAG 依赖
2. 更新 Dockerfile
3. 减小 Backend 镜像体积

---

## 九、监控与运维

### 9.1 健康检查

| 端点 | 用途 | K8s Probe |
|------|------|-----------|
| `/health` | 存活检查 | livenessProbe |
| `/ready` | 就绪检查 | readinessProbe |

### 9.2 指标采集

- OpenTelemetry 兼容
- 关键指标：
  - 请求延迟 (P50/P95/P99)
  - 错误率
  - 活跃流数量

### 9.3 日志规范

- 结构化 JSON 日志
- 请求 ID 追踪
- 错误堆栈完整记录

---

## 十、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 网络延迟 | 索引/检索变慢 | 本地缓存、连接池复用 |
| 服务不可用 | RAG 功能中断 | 本地回退模式 |
| 认证失败 | 请求被拒绝 | 监控告警、快速回滚 |
| 内容获取失败 | 索引中断 | 重试机制、错误上报 |

---

## 十一、验收标准

### 11.1 功能验收

- [ ] 索引操作正常执行
- [ ] 检索返回正确结果
- [ ] 删除操作正常执行
- [ ] 错误响应格式正确
- [ ] 认证中间件正确拦截

### 11.2 性能验收

- [ ] 索引延迟 < 2x 本地模式
- [ ] 检索延迟 < 1.5x 本地模式

### 11.3 运维验收

- [ ] Docker Compose 部署成功
- [ ] 健康检查正常
- [ ] 优雅关闭正常
- [ ] 日志输出正确

---

## 附录 A：错误码定义

| 错误码 | 描述 | retryable |
|--------|------|-----------|
| `invalid_request` | 请求格式错误 | false |
| `unauthorized` | 认证失败 | false |
| `content_fetch_failed` | 内容获取失败 | true |
| `storage_error` | 存储操作失败 | true |
| `embedding_error` | Embedding 调用失败 | true |
| `internal_error` | 内部错误 | true |

## 附录 B：配置变量清单

| 变量名 | 默认值 | 描述 |
|--------|--------|------|
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `8200` | 监听端口 |
| `INTERNAL_SERVICE_TOKEN` | - | 内部服务认证 Token |
| `BACKEND_INTERNAL_URL` | `http://backend:8000` | Backend 内部 URL |
| `GRACEFUL_SHUTDOWN_TIMEOUT` | `30` | 优雅关闭超时秒数 |
| `OTEL_ENABLED` | `false` | OpenTelemetry 开关 |
| `OTEL_SERVICE_NAME` | `wegent-knowledge-runtime` | 服务名称 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | - | OTLP 端点 |

## 附录 C：相关文档

- [RAG 服务拆分落地方案](./2026-03-24-rag-service-split-plan.md)
- [Knowledge Runtime 实现计划](./2026-04-04-rag-service-extraction-implementation-plan.md)
- [动态上下文注入](../zh/developer-guide/dynamic-context.md)
