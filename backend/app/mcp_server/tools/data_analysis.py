# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""
MCP tools for DuckDB data analysis.

Provides AI agents with the ability to inspect table schemas and execute
SQL queries against Excel/CSV attachments that have been imported into
DuckDB. These tools are registered with the data_analysis MCP server.

Tools:
- wegent_data_schema: Get table structure for an attachment
- wegent_data_query: Execute SQL queries against an attachment's DuckDB
"""

import logging
from typing import Any, Dict, Optional

from app.db.session import SessionLocal
from app.mcp_server.auth import TaskTokenInfo
from app.mcp_server.tools.decorator import build_mcp_tools_dict, mcp_tool

logger = logging.getLogger(__name__)


@mcp_tool(
    name="wegent_data_schema",
    description=(
        "Get the table schema for an Excel/CSV attachment. "
        "Returns table names, column names, data types, null counts, and row counts. "
        "Use this tool first to understand the available data before writing SQL queries. "
        "Table names include the 'data_db.' prefix for use in SQL queries."
    ),
    server="data_analysis",
    param_descriptions={
        "attachment_id": "The ID of the attachment to inspect",
    },
)
async def get_data_schema(
    token_info: TaskTokenInfo,
    attachment_id: int,
) -> Dict[str, Any]:
    """Get the table schema for an Excel/CSV attachment.

    Use this tool first to understand the available tables and columns
    before writing SQL queries with wegent_data_query.

    Args:
        token_info: Task token information containing user context.
        attachment_id: The ID of the attachment to inspect.

    Returns:
        Dict with table schema information including names, columns, types, and row counts.
    """
    if not isinstance(attachment_id, int) or attachment_id <= 0:
        return {
            "error": f"Invalid attachment_id: {attachment_id}. Must be a positive integer.",
            "attachment_id": attachment_id,
            "tables": [],
        }

    try:
        from app.services.data_analysis.duckdb_service import duckdb_data_service

        db = SessionLocal()
        try:
            result = await duckdb_data_service.get_schema(
                db=db,
                attachment_id=attachment_id,
            )
            return result
        finally:
            db.close()

    except Exception as e:
        logger.error(
            "Failed to get data schema for attachment %d: %s",
            attachment_id,
            e,
        )
        return {
            "error": f"Failed to get schema: {e}",
            "attachment_id": attachment_id,
            "tables": [],
        }


@mcp_tool(
    name="wegent_data_query",
    description=(
        "Execute a SQL query against an Excel/CSV attachment. "
        "The query runs in read-only mode with temporary table support. "
        "Use 'data_db.' prefix for table names (e.g., data_db.sales_2024). "
        "You can create temporary tables and views for complex multi-step analysis. "
        "Query timeout is 30 seconds, maximum 5000 rows returned."
    ),
    server="data_analysis",
    param_descriptions={
        "attachment_id": "The ID of the attachment to query",
        "sql": "SQL query to execute (SELECT only). Use data_db. prefix for table names.",
    },
)
async def execute_data_query(
    token_info: TaskTokenInfo,
    attachment_id: int,
    sql: str,
) -> Dict[str, Any]:
    """Execute a SQL query against an Excel/CSV attachment.

    The query runs in read-only mode with temporary table support.
    Use data_db. prefix for table names (e.g., data_db.sales_2024).

    Args:
        token_info: Task token information containing user context.
        attachment_id: The ID of the attachment to query.
        sql: SQL query to execute (SELECT only).

    Returns:
        Dict with query results: columns, rows, row_count, and execution metadata.
    """
    if not isinstance(attachment_id, int) or attachment_id <= 0:
        return {
            "error": f"Invalid attachment_id: {attachment_id}. Must be a positive integer.",
            "columns": [],
            "rows": [],
            "row_count": 0,
        }

    if not sql or not sql.strip():
        return {
            "error": "SQL query cannot be empty",
            "columns": [],
            "rows": [],
            "row_count": 0,
        }

    # Validate SQL - only allow SELECT/WITH queries
    normalized_sql = sql.strip().upper()
    if not normalized_sql.startswith("SELECT") and not normalized_sql.startswith("WITH"):
        return {
            "error": "Only SELECT queries are allowed. Use data_db. prefix for table names.",
            "columns": [],
            "rows": [],
            "row_count": 0,
        }

    try:
        from app.services.data_analysis.duckdb_service import duckdb_data_service

        db = SessionLocal()
        try:
            result = await duckdb_data_service.query_duckdb(
                db=db,
                attachment_id=attachment_id,
                sql=sql,
            )
            return result
        finally:
            db.close()

    except Exception as e:
        logger.error(
            "Failed to execute data query for attachment %d: %s",
            attachment_id,
            e,
        )
        return {
            "error": f"Failed to execute query: {e}",
            "columns": [],
            "rows": [],
            "row_count": 0,
        }


# Build tools dict for backward compatibility
DATA_ANALYSIS_MCP_TOOLS = build_mcp_tools_dict(server="data_analysis")
