# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Lightweight transport models for Backend <-> knowledge_runtime.

Refactored to reference-mode: Backend only passes knowledge_base_id and
operation-semantic parameters; Knowledge Runtime resolves all configuration
from the database itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .runtime_config import (
    RetrievalMode,
    RuntimeEmbeddingModelConfig,
    RuntimeRetrievalConfig,
    RuntimeRetrieverConfig,
)


class KnowledgeRuntimeProtocolModel(BaseModel):
    """Base protocol model with strict field validation."""

    model_config = ConfigDict(extra="forbid")


class BackendAttachmentStreamContentRef(KnowledgeRuntimeProtocolModel):
    """Content reference resolved by streaming through Backend."""

    kind: Literal["backend_attachment_stream"]
    url: str
    auth_token: str
    expires_at: datetime | None = None


class PresignedUrlContentRef(KnowledgeRuntimeProtocolModel):
    """Content reference resolved directly from object storage."""

    kind: Literal["presigned_url"]
    url: str
    expires_at: datetime | None = None


ContentRef = Annotated[
    BackendAttachmentStreamContentRef | PresignedUrlContentRef,
    Field(discriminator="kind"),
]

RetrievalPolicy = Literal[
    "chunk_only",
    "summary_first",
    "summary_then_chunk_expand",
    "hybrid",
]


class KnowledgeRuntimeAuth(KnowledgeRuntimeProtocolModel):
    """Simple internal auth carrier for the runtime service."""

    scheme: Literal["bearer"] = "bearer"
    token: str


class RemoteRagError(KnowledgeRuntimeProtocolModel):
    """Standardized remote error payload."""

    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Backward-compatible re-exports (models migrated to runtime_config.py)
# ---------------------------------------------------------------------------
# These re-exports allow existing importers to continue working without
# changes during the migration period.  New code should import directly
# from shared.models.runtime_config.
# ---------------------------------------------------------------------------


class RemoteKnowledgeBaseQueryConfig(KnowledgeRuntimeProtocolModel):
    """Resolved execution config for one queryable knowledge base.

    DEPRECATED: Kept for backward compatibility with runtime_specs.py.
    Knowledge Runtime now resolves this from DB directly.
    """

    knowledge_base_id: int
    index_owner_user_id: int
    retriever_config: RuntimeRetrieverConfig
    embedding_model_config: RuntimeEmbeddingModelConfig
    retrieval_config: RuntimeRetrievalConfig


# ---------------------------------------------------------------------------
# Request models (reference-mode)
# ---------------------------------------------------------------------------


class RemoteIndexRequest(KnowledgeRuntimeProtocolModel):
    """Index request - KR resolves all config from DB by knowledge_base_id."""

    knowledge_base_id: int
    document_id: int | None = None
    user_id: int | None = None
    content_ref: ContentRef
    source_file: str | None = None
    file_extension: str | None = None
    trace_context: dict[str, Any] | None = None
    extensions: dict[str, Any] | None = None
    # KR resolves from DB: index_owner_user_id, retriever_config,
    #   embedding_model_config, splitter_config, index_families, user_name


class RemoteQueryRequest(KnowledgeRuntimeProtocolModel):
    """Query request - KR resolves all config from DB by knowledge_base_ids."""

    knowledge_base_ids: list[int]
    query: str
    max_results: int = Field(default=5, gt=0)
    user_id: int | None = None
    document_ids: list[int] | None = None
    metadata_condition: dict[str, Any] | None = None
    retrieval_policy: RetrievalPolicy = "chunk_only"
    extensions: dict[str, Any] | None = None
    # KR resolves from DB: knowledge_base_configs (with retriever/embedding/retrieval),
    #   index_owner_user_id, enabled_index_families, user_name


class RemoteDeleteDocumentIndexRequest(KnowledgeRuntimeProtocolModel):
    """Delete-document-index request - KR resolves config from DB."""

    knowledge_base_id: int
    document_ref: str
    user_id: int | None = None
    extensions: dict[str, Any] | None = None
    # KR resolves from DB: index_owner_user_id, retriever_config, enabled_index_families


class RemotePurgeKnowledgeIndexRequest(KnowledgeRuntimeProtocolModel):
    """Purge request - KR resolves config from DB."""

    knowledge_base_id: int
    user_id: int | None = None
    extensions: dict[str, Any] | None = None
    # KR resolves from DB: index_owner_user_id, retriever_config


class RemoteDropKnowledgeIndexRequest(KnowledgeRuntimeProtocolModel):
    """Drop request - KR resolves config from DB."""

    knowledge_base_id: int
    user_id: int | None = None
    extensions: dict[str, Any] | None = None
    # KR resolves from DB: index_owner_user_id, retriever_config


class RemoteListChunksRequest(KnowledgeRuntimeProtocolModel):
    """List-chunks request - KR resolves config from DB."""

    knowledge_base_id: int
    max_chunks: int = Field(default=10000, gt=0, le=10000)
    query: str | None = None
    metadata_condition: dict[str, Any] | None = None
    user_id: int | None = None
    extensions: dict[str, Any] | None = None
    # KR resolves from DB: index_owner_user_id, retriever_config


# ---------------------------------------------------------------------------
# Response models (unchanged)
# ---------------------------------------------------------------------------


class RemoteQueryRecord(KnowledgeRuntimeProtocolModel):
    """Single retrieval record returned by knowledge_runtime."""

    content: str
    title: str
    score: float | None = None
    metadata: dict[str, Any] | None = None
    knowledge_base_id: int | None = None
    document_id: int | None = None
    index_family: str = "chunk_vector"


class RemoteQueryResponse(KnowledgeRuntimeProtocolModel):
    """Query response returned by knowledge_runtime."""

    records: list[RemoteQueryRecord]
    total: int
    total_estimated_tokens: int = 0


class RemoteListChunkRecord(KnowledgeRuntimeProtocolModel):
    """Single chunk returned by knowledge_runtime list-chunks endpoint."""

    content: str
    title: str
    chunk_id: int | None = None
    doc_ref: str | None = None
    metadata: dict[str, Any] | None = None


class RemoteListChunksResponse(KnowledgeRuntimeProtocolModel):
    """Chunk listing response returned by knowledge_runtime."""

    chunks: list[RemoteListChunkRecord]
    total: int
