# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Schemas for cloud drive APIs."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.cloud_file import CloudFileSourceType
from app.schemas.knowledge import KnowledgeDocumentResponse, SplitterConfig

CloudFileSort = Literal[
    "created_desc", "created_asc", "name_asc", "name_desc", "size_asc", "size_desc"
]
CloudFileType = Literal[
    "all",
    "image",
    "document",
    "spreadsheet",
    "presentation",
    "pdf",
    "video",
    "audio",
    "text",
    "other",
]


class CloudFileResponse(BaseModel):
    """Cloud drive file item."""

    id: int
    user_id: int
    attachment_id: int
    display_name: str
    file_extension: str = ""
    mime_type: str = ""
    file_size: int = 0
    source_type: str
    source_ref: Dict[str, Any] = Field(default_factory=dict)
    status: str
    text_length: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CloudFileListResponse(BaseModel):
    """Paginated cloud drive file list."""

    items: List[CloudFileResponse]
    total: int
    page: int
    page_size: int


class CloudFileStatsResponse(BaseModel):
    """Cloud drive statistics."""

    total_count: int
    total_size: int


class CloudFileImportToKnowledgeRequest(BaseModel):
    """Request for importing cloud drive files into a knowledge base."""

    knowledge_base_id: int = Field(..., gt=0)
    file_ids: List[int] = Field(..., min_length=1)
    folder_id: int = Field(default=0, ge=0)
    splitter_config: Optional[SplitterConfig] = None


class CloudFileImportItem(BaseModel):
    """Per-file import result."""

    cloud_file_id: int
    status: Literal["success", "failed"]
    document_id: Optional[int] = None
    attachment_id: Optional[int] = None
    error: Optional[str] = None


class CloudFileImportToKnowledgeResponse(BaseModel):
    """Batch import result."""

    success_count: int
    failed_count: int
    items: List[CloudFileImportItem]


class CloudFileRecordOptions(BaseModel):
    """Options for recording a cloud file index."""

    source_type: CloudFileSourceType = CloudFileSourceType.UNKNOWN
    source_ref: Dict[str, Any] = Field(default_factory=dict)
