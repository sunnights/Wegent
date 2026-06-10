# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""add cloud files table

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-06-10

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the cloud drive directory index table."""
    op.create_table(
        "cloud_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("attachment_id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "file_extension", sa.String(length=32), nullable=False, server_default=""
        ),
        sa.Column(
            "mime_type", sa.String(length=255), nullable=False, server_default=""
        ),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "source_type",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("source_ref", sa.JSON(), nullable=False),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "attachment_id", name="uq_cloud_files_user_attachment"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_cloud_files_id", "cloud_files", ["id"])
    op.create_index("ix_cloud_files_user_id", "cloud_files", ["user_id"])
    op.create_index("ix_cloud_files_attachment_id", "cloud_files", ["attachment_id"])
    op.create_index("ix_cloud_files_is_deleted", "cloud_files", ["is_deleted"])
    op.create_index(
        "ix_cloud_files_user_deleted_created",
        "cloud_files",
        ["user_id", "is_deleted", "created_at"],
    )
    op.create_index(
        "ix_cloud_files_user_source", "cloud_files", ["user_id", "source_type"]
    )
    op.create_index(
        "ix_cloud_files_user_display_name",
        "cloud_files",
        ["user_id", "display_name"],
    )


def downgrade() -> None:
    """Drop the cloud drive directory index table."""
    op.drop_index("ix_cloud_files_user_display_name", table_name="cloud_files")
    op.drop_index("ix_cloud_files_user_source", table_name="cloud_files")
    op.drop_index("ix_cloud_files_user_deleted_created", table_name="cloud_files")
    op.drop_index("ix_cloud_files_is_deleted", table_name="cloud_files")
    op.drop_index("ix_cloud_files_attachment_id", table_name="cloud_files")
    op.drop_index("ix_cloud_files_user_id", table_name="cloud_files")
    op.drop_index("ix_cloud_files_id", table_name="cloud_files")
    op.drop_table("cloud_files")
