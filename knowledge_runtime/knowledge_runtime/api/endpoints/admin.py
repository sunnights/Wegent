# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Admin endpoints for knowledge base management operations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from knowledge_runtime.services.admin_executor import AdminExecutor
from shared.db.sync_session import get_db
from shared.models import (
    RemoteDeleteDocumentIndexRequest,
    RemoteDropKnowledgeIndexRequest,
    RemoteListChunksRequest,
    RemoteListChunksResponse,
    RemotePurgeKnowledgeIndexRequest,
)

router = APIRouter()


@router.post("/delete-document-index")
async def delete_document_index(
    request: RemoteDeleteDocumentIndexRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete a document's index from a knowledge base.

    Args:
        request: The delete request with knowledge_base_id reference.
        db: Database session for config resolution.

    Returns:
        Deletion result.
    """
    executor = AdminExecutor(db=db)
    return await executor.delete_document_index(request)


@router.post("/purge-knowledge-index")
async def purge_knowledge_index(
    request: RemotePurgeKnowledgeIndexRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete all chunks for a knowledge base.

    Args:
        request: The purge request with knowledge_base_id reference.
        db: Database session for config resolution.

    Returns:
        Purge result.
    """
    executor = AdminExecutor(db=db)
    return await executor.purge_knowledge_index(request)


@router.post("/drop-knowledge-index")
async def drop_knowledge_index(
    request: RemoteDropKnowledgeIndexRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Physically drop the index/collection for a knowledge base.

    Args:
        request: The drop request with knowledge_base_id reference.
        db: Database session for config resolution.

    Returns:
        Drop result.
    """
    executor = AdminExecutor(db=db)
    return await executor.drop_knowledge_index(request)


@router.post("/all-chunks")
async def list_chunks(
    request: RemoteListChunksRequest,
    db: Session = Depends(get_db),
) -> RemoteListChunksResponse:
    """List all chunks in a knowledge base.

    Args:
        request: The list request with knowledge_base_id reference.
        db: Database session for config resolution.

    Returns:
        List of chunks.
    """
    executor = AdminExecutor(db=db)
    return await executor.list_chunks(request)
