# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Query execution service for RAG retrieval operations."""

from __future__ import annotations

import logging
from typing import Any

from knowledge_engine.embedding.factory import (
    create_embedding_model_from_runtime_config,
)
from knowledge_engine.query.executor import QueryExecutor as KnowledgeQueryExecutor
from knowledge_engine.storage.factory import create_storage_backend_from_runtime_config
from knowledge_runtime.services.config_resolver import KnowledgeRuntimeConfigResolver
from shared.models import (
    RemoteQueryRecord,
    RemoteQueryRequest,
    RemoteQueryResponse,
)
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class QueryExecutor:
    """Executes RAG query operations.

    This executor:
    1. Resolves all configuration from DB using knowledge_base_ids reference
    2. Creates storage backends and embedding models for each knowledge base
    3. Executes queries against each KB
    4. Aggregates and sorts results by score
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._config_resolver = KnowledgeRuntimeConfigResolver()

    async def execute(self, request: RemoteQueryRequest) -> RemoteQueryResponse:
        """Execute the query operation.

        Args:
            request: The query request containing query text and knowledge_base_ids.

        Returns:
            Query response with ranked records.
        """
        # Resolve all KB configs from DB
        resolved_configs = self._config_resolver.resolve_query_configs(
            self._db,
            knowledge_base_ids=request.knowledge_base_ids,
            user_id=request.user_id,
        )

        all_records: list[RemoteQueryRecord] = []

        # Query each knowledge base
        for resolved in resolved_configs:
            records = await self._query_knowledge_base(
                request=request,
                resolved=resolved,
            )
            all_records.extend(records)

        # Sort by score (descending) and limit to max_results
        all_records.sort(key=lambda r: r.score or 0, reverse=True)
        limited_records = all_records[: request.max_results]

        # Calculate total estimated tokens (rough estimate)
        total_tokens = sum(
            self._estimate_tokens(record.content) for record in limited_records
        )

        logger.info(
            "Query complete: query='%s...', total_results=%d, returned=%d",
            request.query[:50],
            len(all_records),
            len(limited_records),
        )

        return RemoteQueryResponse(
            records=limited_records,
            total=len(all_records),
            total_estimated_tokens=total_tokens,
        )

    async def _query_knowledge_base(
        self,
        request: RemoteQueryRequest,
        resolved: Any,
    ) -> list[RemoteQueryRecord]:
        """Query a single knowledge base.

        Args:
            request: The original query request.
            resolved: Resolved configuration for this specific knowledge base.

        Returns:
            List of records from this knowledge base.
        """
        # Create storage backend
        storage_backend = create_storage_backend_from_runtime_config(
            resolved.retriever_config
        )

        # Create embedding model
        embed_model = create_embedding_model_from_runtime_config(
            resolved.embedding_model_config
        )

        # Create query executor
        executor = KnowledgeQueryExecutor(
            storage_backend=storage_backend,
            embed_model=embed_model,
        )

        # Build knowledge_id
        knowledge_id = str(resolved.knowledge_base_id)

        # Execute query
        result = await executor.execute(
            knowledge_id=knowledge_id,
            query=request.query,
            retrieval_config=resolved.retrieval_config,
            metadata_condition=request.metadata_condition,
            user_id=resolved.index_owner_user_id,
        )

        # Convert to RemoteQueryRecord format
        records: list[RemoteQueryRecord] = []
        for record in result.get("records", []):
            records.append(
                RemoteQueryRecord(
                    content=record.get("content", ""),
                    title=record.get("title", ""),
                    score=record.get("score"),
                    metadata=record.get("metadata"),
                    knowledge_base_id=resolved.knowledge_base_id,
                    document_id=self._extract_document_id(record),
                )
            )

        logger.info(
            "Queried KB: knowledge_base_id=%d, records=%d",
            resolved.knowledge_base_id,
            len(records),
        )

        return records

    def _extract_document_id(self, record: dict[str, Any]) -> int | None:
        """Extract document ID from record metadata.

        Args:
            record: Query result record.

        Returns:
            Document ID if found, None otherwise.
        """
        metadata = record.get("metadata") or {}
        doc_ref = metadata.get("doc_ref")
        if doc_ref and isinstance(doc_ref, str):
            try:
                # doc_ref format is typically "doc_xxx" or numeric string
                if doc_ref.startswith("doc_"):
                    return int(doc_ref[4:])
                return int(doc_ref)
            except ValueError:
                pass
        return None

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Uses a simple heuristic: ~4 characters per token.

        Args:
            text: Text to estimate tokens for.

        Returns:
            Estimated token count.
        """
        return len(text) // 4
