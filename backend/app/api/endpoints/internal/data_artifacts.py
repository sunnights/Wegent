# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Internal endpoint for uploading DuckDB artifact files.

Used by knowledge_runtime to upload generated .duckdb files
to Backend storage, reusing the existing ContextService and
StorageBackend infrastructure.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.services.context import context_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data/artifacts", tags=["internal-data-artifacts"])


@router.post("/upload")
async def upload_duckdb_artifact(
    attachment_id: int = Form(...),
    original_filename: str = Form(...),
    file_extension: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Upload a .duckdb file as an internal attachment.

    This endpoint is called by knowledge_runtime after generating a .duckdb
    file from an Excel/CSV attachment. The file is stored via the existing
    ContextService upload_attachment method, returning a new attachment_id
    for the .duckdb file.

    Args:
        attachment_id: The original attachment ID this DuckDB was generated from.
        original_filename: Filename for the .duckdb artifact.
        file_extension: File extension (should be .duckdb).
        file: The .duckdb binary file.
        db: Database session.

    Returns:
        Dict with the new attachment_id for the .duckdb file.
    """
    try:
        binary_data = await file.read()
        if not binary_data:
            raise HTTPException(status_code=400, detail="Empty file")

        # Use user_id=0 for internal service uploads
        # The .duckdb file is a system artifact, not user-owned
        context, _ = context_service.upload_attachment(
            db=db,
            user_id=0,
            filename=original_filename,
            binary_data=binary_data,
            subtask_id=0,  # Unlinked from any specific subtask
        )

        logger.info(
            "Uploaded DuckDB artifact for original attachment %d, "
            "new attachment_id=%d, size=%d bytes",
            attachment_id,
            context.id,
            len(binary_data),
        )

        return {
            "attachment_id": context.id,
            "file_size": len(binary_data),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to upload DuckDB artifact for attachment %d: %s",
            attachment_id,
            e,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload DuckDB artifact: {e}",
        )
