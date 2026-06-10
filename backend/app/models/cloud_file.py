# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Cloud drive directory index model."""

from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.db.base import Base


class CloudFileSourceType(str, Enum):
    """Supported source types for cloud drive files."""

    CHAT = "chat"
    KNOWLEDGE = "knowledge"
    CLOUD_DRIVE = "cloud_drive"
    OPEN_API = "open_api"
    EXECUTOR = "executor"
    INBOX = "inbox"
    CHANNEL = "channel"
    UNKNOWN = "unknown"


class CloudFile(Base):
    """Lightweight cloud drive index pointing to an attachment context."""

    __tablename__ = "cloud_files"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    attachment_id = Column(Integer, nullable=False, index=True)
    display_name = Column(String(255), nullable=False)
    file_extension = Column(String(32), nullable=False, default="")
    mime_type = Column(String(255), nullable=False, default="")
    file_size = Column(Integer, nullable=False, default=0)
    source_type = Column(
        String(32), nullable=False, default=CloudFileSourceType.UNKNOWN.value
    )
    source_ref = Column(JSON, nullable=False, default=dict)
    is_deleted = Column(Boolean, nullable=False, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "attachment_id", name="uq_cloud_files_user_attachment"
        ),
        Index(
            "ix_cloud_files_user_deleted_created", "user_id", "is_deleted", "created_at"
        ),
        Index("ix_cloud_files_user_source", "user_id", "source_type"),
        Index("ix_cloud_files_user_display_name", "user_id", "display_name"),
        {
            "sqlite_autoincrement": True,
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )
