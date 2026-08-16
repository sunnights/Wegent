# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Mapping from an external resource snapshot to a Wegent document."""

from sqlalchemy import Column, Index, Integer, String

from app.db.base import Base


class ExternalKnowledgeSnapshot(Base):
    """Stable identity for an imported external knowledge document."""

    __tablename__ = "external_knowledge_snapshots"

    id = Column(Integer, primary_key=True)
    knowledge_base_id = Column(Integer, nullable=False)
    provider = Column(String(32), nullable=False)
    external_resource_id = Column(String(255), nullable=False)
    source_url = Column(String(2048), nullable=False)
    document_id = Column(Integer, nullable=False)

    __table_args__ = (
        Index(
            "uq_external_snapshot_resource",
            "knowledge_base_id",
            "provider",
            "external_resource_id",
            unique=True,
        ),
        Index("uq_external_snapshot_document", "document_id", unique=True),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
            "comment": "External resource to Wegent knowledge document mapping",
        },
    )
