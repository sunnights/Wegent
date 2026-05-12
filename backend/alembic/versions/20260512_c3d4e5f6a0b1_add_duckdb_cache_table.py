# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""add duckdb_cache table

Revision ID: c3d4e5f6a0b1
Revises: b2c3d4e5f707
Create Date: 2026-05-12

Add duckdb_cache table for tracking DuckDB files generated from
Excel/CSV attachments. Stores metadata including the relationship
between original attachments and their .duckdb counterparts,
SUMMARIZE results, and integrity hashes.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c3d4e5f6a0b1"
down_revision = "b2c3d4e5f707"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "duckdb_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "attachment_id",
            sa.Integer(),
            nullable=False,
            comment="Original attachment ID (references subtask_contexts.id)",
        ),
        sa.Column(
            "duckdb_attachment_id",
            sa.Integer(),
            nullable=False,
            comment="DuckDB file attachment ID (references subtask_contexts.id)",
        ),
        sa.Column(
            "summary",
            sa.JSON(),
            nullable=True,
            comment="SUMMARIZE results + sample data for AI context",
        ),
        sa.Column(
            "tables_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Number of tables in the DuckDB file",
        ),
        sa.Column(
            "file_size",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
            comment="DuckDB file size in bytes",
        ),
        sa.Column(
            "source_file_hash",
            sa.String(64),
            nullable=True,
            comment="SHA256 hash of the original source file for integrity check",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="generating",
            comment="Status: generating, ready, failed",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
        comment="DuckDB cache metadata for Excel/CSV data analysis",
    )
    op.create_index(
        "ix_duckdb_cache_attachment_id",
        "duckdb_cache",
        ["attachment_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_duckdb_cache_id"),
        "duckdb_cache",
        ["id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_duckdb_cache_id"), table_name="duckdb_cache")
    op.drop_index("ix_duckdb_cache_attachment_id", table_name="duckdb_cache")
    op.drop_table("duckdb_cache")
