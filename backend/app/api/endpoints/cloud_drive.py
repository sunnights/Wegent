# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Cloud drive API endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core import security
from app.models.cloud_file import CloudFileSourceType
from app.models.user import User
from app.schemas.cloud_file import (
    CloudFileImportToKnowledgeRequest,
    CloudFileImportToKnowledgeResponse,
    CloudFileListResponse,
    CloudFileStatsResponse,
)
from app.schemas.subtask_context import AttachmentResponse
from app.services.attachment.parser import DocumentParseError, DocumentParser
from app.services.cloud_file_service import cloud_file_service
from app.services.context import context_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/files", response_model=CloudFileListResponse)
def list_files(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    query: Optional[str] = Query(default=None),
    source_type: Optional[str] = Query(default=None),
    file_type: str = Query(default="all"),
    sort: str = Query(default="created_desc"),
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_user),
):
    """List visible cloud drive files for the current user."""
    return cloud_file_service.list_files(
        db=db,
        user_id=current_user.id,
        page=page,
        page_size=page_size,
        query=query,
        source_type=source_type,
        file_type=file_type,
        sort=sort,
    )


@router.get("/stats", response_model=CloudFileStatsResponse)
def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_user),
):
    """Return cloud drive stats for the current user."""
    return cloud_file_service.get_stats(db=db, user_id=current_user.id)


@router.post("/files/upload", response_model=AttachmentResponse)
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_user),
):
    """Upload a file directly into the cloud drive."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    try:
        binary_data = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail="Failed to read uploaded file"
        ) from exc
    if not DocumentParser.validate_file_size(len(binary_data)):
        max_size_mb = DocumentParser.get_max_file_size() / (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds maximum limit ({max_size_mb} MB)",
        )

    try:
        context, truncation_info = context_service.upload_attachment(
            db=db,
            user_id=current_user.id,
            filename=file.filename,
            binary_data=binary_data,
            subtask_id=0,
        )
        cloud_file_service.record_attachment_created(
            db=db,
            context=context,
            source_type=CloudFileSourceType.CLOUD_DRIVE,
        )
        return AttachmentResponse.from_context(context, truncation_info)
    except DocumentParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Cloud drive upload failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to upload file") from exc


@router.post("/files/{file_id}/copy-to-attachment", response_model=AttachmentResponse)
def copy_to_attachment(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_user),
):
    """Copy a cloud drive file into a new unlinked attachment."""
    try:
        return cloud_file_service.copy_to_attachment(
            db=db, file_id=file_id, user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Cloud drive copy failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to copy file") from exc


@router.delete("/files/{file_id}", status_code=204)
def delete_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_user),
):
    """Soft-delete a cloud drive file index."""
    try:
        cloud_file_service.soft_delete(db=db, file_id=file_id, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/files/import-to-knowledge",
    response_model=CloudFileImportToKnowledgeResponse,
)
def import_to_knowledge(
    request: CloudFileImportToKnowledgeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_user),
):
    """Import cloud drive files into a knowledge base."""
    splitter_config = (
        request.splitter_config.model_dump(exclude_none=True)
        if request.splitter_config
        else None
    )
    return cloud_file_service.import_to_knowledge(
        db=db,
        user=current_user,
        knowledge_base_id=request.knowledge_base_id,
        file_ids=request.file_ids,
        folder_id=request.folder_id,
        splitter_config=splitter_config,
    )
