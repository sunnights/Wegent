# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest
from pydantic import ValidationError

import shared.models as shared_models


def _require_model(name: str):
    model = getattr(shared_models, name, None)
    if model is None:
        pytest.fail(f"shared.models must export {name}")
    return model


def test_shared_models_exports_knowledge_runtime_protocol_types() -> None:
    exported_names = [
        "BackendAttachmentStreamContentRef",
        "PresignedUrlContentRef",
        "RuntimeEmbeddingModelConfig",
        "RuntimeRetrievalConfig",
        "RuntimeRetrieverConfig",
        "RemoteKnowledgeBaseQueryConfig",
        "RemoteDeleteDocumentIndexRequest",
        "RemoteIndexRequest",
        "RemoteListChunksRequest",
        "RemoteListChunksResponse",
        "RemoteListChunkRecord",
        "RemoteQueryRequest",
        "RemoteQueryRecord",
        "RemoteQueryResponse",
        # RemoteTestConnectionRequest removed (KR test-connection endpoint deleted)
    ]

    for name in exported_names:
        assert getattr(shared_models, name, None) is not None


def test_remote_index_request_reference_mode() -> None:
    """Test RemoteIndexRequest with reference-mode (knowledge_base_id only)."""
    remote_index_request = _require_model("RemoteIndexRequest")

    request = remote_index_request.model_validate(
        {
            "knowledge_base_id": 11,
            "document_id": 22,
            "user_id": 42,
            "content_ref": {
                "kind": "backend_attachment_stream",
                "url": "http://backend:8000/api/internal/rag/content/22",
                "auth_token": "test-token",
            },
        }
    )

    assert request.knowledge_base_id == 11
    assert request.document_id == 22
    assert request.user_id == 42
    assert request.content_ref.kind == "backend_attachment_stream"
    assert request.content_ref.auth_token == "test-token"


def test_remote_index_request_rejects_unknown_content_ref_kind() -> None:
    remote_index_request = _require_model("RemoteIndexRequest")

    with pytest.raises(ValidationError):
        remote_index_request.model_validate(
            {
                "knowledge_base_id": 11,
                "content_ref": {
                    "kind": "unsupported_kind",
                    "url": "http://backend:8000/api/internal/rag/content/22",
                },
            }
        )


def test_remote_index_request_rejects_old_value_mode_fields() -> None:
    """Verify that old value-mode fields (retriever_config, etc.) are rejected."""
    remote_index_request = _require_model("RemoteIndexRequest")

    with pytest.raises(ValidationError):
        remote_index_request.model_validate(
            {
                "knowledge_base_id": 11,
                "content_ref": {
                    "kind": "presigned_url",
                    "url": "http://example.com/file.pdf",
                },
                # These fields are no longer accepted
                "retriever_config": {
                    "name": "retriever-a",
                    "namespace": "default",
                    "storage_config": {"type": "milvus", "url": "http://milvus:19530"},
                },
            }
        )


def test_remote_query_response_preserves_index_family_per_record() -> None:
    remote_query_response = _require_model("RemoteQueryResponse")

    response = remote_query_response.model_validate(
        {
            "records": [
                {
                    "content": "Chunk A",
                    "title": "Doc A",
                    "score": 0.91,
                    "knowledge_base_id": 1001,
                    "index_family": "chunk_vector",
                },
                {
                    "content": "Summary B",
                    "title": "Doc B",
                    "score": 0.88,
                    "knowledge_base_id": 1002,
                    "index_family": "summary_vector",
                },
            ],
            "total": 2,
        }
    )

    assert [record.index_family for record in response.records] == [
        "chunk_vector",
        "summary_vector",
    ]


def test_remote_list_chunks_request_reference_mode() -> None:
    """Test RemoteListChunksRequest with reference-mode (knowledge_base_id only)."""
    remote_list_chunks_request = _require_model("RemoteListChunksRequest")

    request = remote_list_chunks_request.model_validate(
        {
            "knowledge_base_id": 1001,
            "max_chunks": 1000,
            "query": "list_index_chunks",
            "metadata_condition": {
                "operator": "and",
                "conditions": [
                    {"key": "lang", "operator": "==", "value": "zh"},
                ],
            },
            "user_id": 42,
        }
    )

    assert request.knowledge_base_id == 1001
    assert request.max_chunks == 1000
    assert request.metadata_condition == {
        "operator": "and",
        "conditions": [
            {"key": "lang", "operator": "==", "value": "zh"},
        ],
    }


def test_remote_query_request_reference_mode() -> None:
    """Test RemoteQueryRequest with reference-mode (knowledge_base_ids only)."""
    remote_query_request = _require_model("RemoteQueryRequest")

    request = remote_query_request.model_validate(
        {
            "knowledge_base_ids": [1001],
            "query": "release checklist",
            "max_results": 6,
            "user_id": 42,
            "metadata_condition": {
                "operator": "or",
                "conditions": [
                    {"key": "source", "operator": "==", "value": "kb"},
                    {"key": "lang", "operator": "==", "value": "zh"},
                ],
            },
            "retrieval_policy": "summary_then_chunk_expand",
        }
    )

    assert request.knowledge_base_ids == [1001]
    assert request.query == "release checklist"
    assert request.retrieval_policy == "summary_then_chunk_expand"
    assert request.user_id == 42


def test_remote_query_request_rejects_old_value_mode_fields() -> None:
    """Verify that old value-mode fields (knowledge_base_configs, etc.) are rejected."""
    remote_query_request = _require_model("RemoteQueryRequest")

    with pytest.raises(ValidationError):
        remote_query_request.model_validate(
            {
                "knowledge_base_ids": [1001],
                "query": "release checklist",
                # These fields are no longer accepted
                "knowledge_base_configs": [
                    {
                        "knowledge_base_id": 1001,
                        "index_owner_user_id": 42,
                        "retriever_config": {
                            "name": "retriever-a",
                            "namespace": "default",
                            "storage_config": {"type": "qdrant", "url": "http://qdrant:6333"},
                        },
                        "embedding_model_config": {
                            "model_name": "embed-a",
                            "model_namespace": "default",
                            "resolved_config": {"protocol": "openai"},
                        },
                        "retrieval_config": {
                            "top_k": 8,
                            "score_threshold": 0.55,
                        },
                    }
                ],
            }
        )


def test_remote_delete_request_reference_mode() -> None:
    """Test RemoteDeleteDocumentIndexRequest with reference-mode."""
    remote_delete_request = _require_model("RemoteDeleteDocumentIndexRequest")

    request = remote_delete_request.model_validate(
        {
            "knowledge_base_id": 101,
            "document_ref": "202",
            "user_id": 303,
        }
    )

    assert request.knowledge_base_id == 101
    assert request.document_ref == "202"
    assert request.user_id == 303


def test_remote_purge_request_reference_mode() -> None:
    """Test RemotePurgeKnowledgeIndexRequest with reference-mode."""
    remote_purge_request = _require_model("RemotePurgeKnowledgeIndexRequest")

    request = remote_purge_request.model_validate(
        {
            "knowledge_base_id": 101,
            "user_id": 42,
        }
    )

    assert request.knowledge_base_id == 101


def test_remote_drop_request_reference_mode() -> None:
    """Test RemoteDropKnowledgeIndexRequest with reference-mode."""
    remote_drop_request = _require_model("RemoteDropKnowledgeIndexRequest")

    request = remote_drop_request.model_validate(
        {
            "knowledge_base_id": 101,
            "user_id": 42,
        }
    )

    assert request.knowledge_base_id == 101


@pytest.mark.parametrize(
    ("model_name", "payload"),
    [
        (
            "RuntimeRetrievalConfig",
            {
                "top_k": 0,
                "score_threshold": 0.7,
                "retrieval_mode": "vector",
            },
        ),
        (
            "RuntimeRetrievalConfig",
            {
                "top_k": 5,
                "score_threshold": 1.5,
                "retrieval_mode": "vector",
            },
        ),
        (
            "RemoteQueryRequest",
            {
                "knowledge_base_ids": [1],
                "query": "release",
                "max_results": 0,
            },
        ),
        (
            "RemoteListChunksRequest",
            {
                "knowledge_base_id": 1001,
                "max_chunks": 10001,
            },
        ),
    ],
)
def test_protocol_models_reject_invalid_numeric_ranges(
    model_name: str,
    payload: dict,
) -> None:
    model = _require_model(model_name)

    with pytest.raises(ValidationError):
        model.model_validate(payload)
