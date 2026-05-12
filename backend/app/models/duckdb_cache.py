# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""DuckDBCache model for tracking generated .duckdb files.

Stores metadata about DuckDB files generated from Excel/CSV attachments,
including the relationship between original attachments and their
.duckdb counterparts, summary data, and integrity information.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.mysql import JSON, LONGBLOB

from app.db.base import Base


class DuckDBCache(Base):
    """Cache metadata for DuckDB files generated from Excel/CSV attachments.

    Links the original attachment (SubtaskContext with Excel/CSV data) to
    its corresponding .duckdb file (another SubtaskContext). The summary
    field stores SUMMARIZE results and sample data for AI context injection.
    """

    __tablename__ = "duckdb_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    attachment_id = Column(
        Integer,
        nullable=False,
        unique=True,
        comment="Original attachment ID (references subtask_contexts.id)",
    )
    duckdb_attachment_id = Column(
        Integer,
        nullable=False,
        comment="DuckDB file attachment ID (references subtask_contexts.id)",
    )
    summary = Column(
        JSON,
        nullable=True,
        comment="SUMMARIZE results + sample data for AI context",
    )
    tables_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of tables in the DuckDB file",
    )
    file_size = Column(
        BigInteger,
        nullable=False,
        default=0,
        comment="DuckDB file size in bytes",
    )
    source_file_hash = Column(
        String(64),
        nullable=True,
        comment="SHA256 hash of the original source file for integrity check",
    )
    status = Column(
        String(20),
        nullable=False,
        default="generating",
        comment="Status: generating, ready, failed",
    )
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
