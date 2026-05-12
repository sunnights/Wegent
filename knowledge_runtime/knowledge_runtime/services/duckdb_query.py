# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""DuckDB query service for executing SQL against cached .duckdb files.

Uses :memory: + ATTACH read-only mode for safe, concurrent queries
with temporary table/view support.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

from knowledge_runtime.config import get_settings
from knowledge_runtime.services.duckdb_manager import get_duckdb_manager

logger = logging.getLogger(__name__)


class DuckDBQueryService:
    """Executes SQL queries against cached .duckdb files."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._manager = get_duckdb_manager()

    def execute_query(
        self,
        attachment_id: int,
        sql: str,
    ) -> dict[str, Any]:
        """Execute a SQL query against an attachment's DuckDB file.

        Uses :memory: + ATTACH read-only for safe concurrent access.
        Table names must use the data_db. prefix.

        Args:
            attachment_id: The attachment ID whose DuckDB to query.
            sql: SQL query to execute.

        Returns:
            Dict with query results: columns, rows, row_count, etc.
        """
        start_time = time.time()

        # Validate SQL - only allow SELECT queries
        normalized_sql = sql.strip().upper()
        if not normalized_sql.startswith("SELECT") and not normalized_sql.startswith("WITH"):
            return {
                "success": False,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "total_count": None,
                "execution_time_ms": 0,
                "truncated": False,
                "error": "Only SELECT queries are allowed. Use data_db. prefix for table names.",
            }

        # Check if cached file exists
        duckdb_path = self._manager.get_duckdb_path(attachment_id)
        if not duckdb_path.exists():
            return {
                "success": False,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "total_count": None,
                "execution_time_ms": 0,
                "truncated": False,
                "error": f"No DuckDB cache found for attachment {attachment_id}. Please upload the file first.",
            }

        try:
            import duckdb
        except ImportError:
            return {
                "success": False,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "total_count": None,
                "execution_time_ms": 0,
                "truncated": False,
                "error": "DuckDB is not installed",
            }

        conn = None
        try:
            # Create :memory: connection and ATTACH the data file read-only
            conn = duckdb.connect(":memory:")
            conn.execute(f"ATTACH '{duckdb_path}' (READ_ONLY) AS data_db")
            # Disable external access for security - data is already ATTACHed
            conn.execute("SET enable_external_access = false")
            conn.execute(f"SET statement_timeout = '{self._settings.duckdb_query_timeout}s'")

            # Execute the query
            result = conn.execute(sql)

            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()

            # Apply row limit
            max_rows = self._settings.duckdb_max_query_rows
            truncated = len(rows) > max_rows
            if truncated:
                rows = rows[:max_rows]

            # Try to get total count if query has LIMIT
            total_count = None
            if _has_limit_clause(sql):
                try:
                    count_sql = _build_count_query(sql)
                    count_result = conn.execute(count_sql).fetchone()
                    total_count = count_result[0] if count_result else len(rows)
                except Exception:
                    # If count query fails, just use the row count
                    total_count = None

            elapsed_ms = (time.time() - start_time) * 1000

            return {
                "success": True,
                "columns": columns,
                "rows": [list(row) for row in rows],
                "row_count": len(rows),
                "total_count": total_count,
                "execution_time_ms": round(elapsed_ms, 2),
                "truncated": truncated,
                "error": None,
            }

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(
                "DuckDB query failed for attachment %d: %s", attachment_id, e
            )
            return {
                "success": False,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "total_count": None,
                "execution_time_ms": round(elapsed_ms, 2),
                "truncated": False,
                "error": str(e),
            }
        finally:
            if conn is not None:
                conn.close()

    def get_schema(self, attachment_id: int) -> dict[str, Any]:
        """Get the table schema for an attachment's DuckDB file.

        Args:
            attachment_id: The attachment ID to inspect.

        Returns:
            Dict with table schema information.
        """
        duckdb_path = self._manager.get_duckdb_path(attachment_id)
        if not duckdb_path.exists():
            return {
                "attachment_id": attachment_id,
                "tables": [],
                "error": f"No DuckDB cache found for attachment {attachment_id}",
            }

        try:
            import duckdb
        except ImportError:
            return {
                "attachment_id": attachment_id,
                "tables": [],
                "error": "DuckDB is not installed",
            }

        conn = None
        try:
            conn = duckdb.connect(":memory:")
            conn.execute(f"ATTACH '{duckdb_path}' (READ_ONLY) AS data_db")
            conn.execute("SET enable_external_access = false")

            # Get all tables in the attached database
            tables_result = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_catalog = 'data_db' AND table_schema = 'main'"
            ).fetchall()

            tables = []
            for (table_name,) in tables_result:
                # Get row count
                count_result = conn.execute(
                    f"SELECT COUNT(*) FROM data_db.{table_name}"
                ).fetchone()
                row_count = count_result[0] if count_result else 0

                # Get column info
                columns_result = conn.execute(
                    f"SELECT column_name, data_type FROM information_schema.columns "
                    f"WHERE table_catalog = 'data_db' AND table_schema = 'main' "
                    f"AND table_name = '{table_name}' "
                    f"ORDER BY ordinal_position"
                ).fetchall()

                # Get null counts per column
                columns = []
                for col_name, col_type in columns_result:
                    null_count_result = conn.execute(
                        f"SELECT COUNT(*) FROM data_db.{table_name} WHERE {col_name} IS NULL"
                    ).fetchone()
                    null_count = null_count_result[0] if null_count_result else 0

                    columns.append({
                        "name": col_name,
                        "type": col_type,
                        "null_count": null_count,
                    })

                tables.append({
                    "name": f"data_db.{table_name}",
                    "rows": row_count,
                    "columns": columns,
                })

            return {
                "attachment_id": attachment_id,
                "tables": tables,
                "error": None,
            }

        except Exception as e:
            logger.error(
                "Failed to get schema for attachment %d: %s", attachment_id, e
            )
            return {
                "attachment_id": attachment_id,
                "tables": [],
                "error": str(e),
            }
        finally:
            if conn is not None:
                conn.close()


def _has_limit_clause(sql: str) -> bool:
    """Check if a SQL query has a LIMIT clause."""
    # Simple check - look for LIMIT outside of subqueries
    upper = sql.upper()
    return "LIMIT" in upper


def _build_count_query(sql: str) -> str:
    """Build a COUNT query from a SELECT query with LIMIT.

    Wraps the original query as a subquery and counts total rows.
    """
    return f"SELECT COUNT(*) FROM ({sql}) AS _count_wrapper"
