# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Add external knowledge snapshot mapping.

Revision ID: c9d8e7f6a5b4
Revises: c8d9e0f1a2b3
Create Date: 2026-08-16
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c9d8e7f6a5b4"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "external_knowledge_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("knowledge_base_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_resource_id", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="External resource to Wegent knowledge document mapping",
    )
    op.create_index(
        "uq_external_snapshot_resource",
        "external_knowledge_snapshots",
        ["knowledge_base_id", "provider", "external_resource_id"],
        unique=True,
    )
    op.create_index(
        "uq_external_snapshot_document",
        "external_knowledge_snapshots",
        ["document_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_external_snapshot_document",
        table_name="external_knowledge_snapshots",
    )
    op.drop_index(
        "uq_external_snapshot_resource",
        table_name="external_knowledge_snapshots",
    )
    op.drop_table("external_knowledge_snapshots")
