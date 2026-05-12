# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Data analysis endpoints for DuckDB generation and SQL query execution."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter

from knowledge_runtime.services.artifact_uploader import get_artifact_uploader
from knowledge_runtime.services.content_fetcher import ContentFetcher
from knowledge_runtime.services.duckdb_generator import DuckDBGenerator
from knowledge_runtime.services.duckdb_manager import get_duckdb_manager
from knowledge_runtime.services.duckdb_query import DuckDBQueryService
from shared.models import (
    RemoteDataGenerateRequest,
    RemoteDataGenerateResponse,
    RemoteDataQueryRequest,
    RemoteDataQueryResponse,
    RemoteDataSchemaResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Service instances
_generator = DuckDBGenerator()
_query_service = DuckDBQueryService()
_content_fetcher = ContentFetcher()


@router.post("/generate", response_model=RemoteDataGenerateResponse)
async def generate_duckdb(
    request: RemoteDataGenerateRequest,
) -> Any:
    """Generate a .duckdb file from an Excel/CSV attachment.

    Fetches the source file via ContentRef, imports into DuckDB,
    generates SUMMARIZE + sample data, and optionally uploads the
    .duckdb file to Backend storage.

    Args:
        request: The generate request with attachment_id and content_ref.

    Returns:
        RemoteDataGenerateResponse with generation results.
    """
    logger.info(
        "Generating DuckDB for attachment %d", request.attachment_id
    )

    # Check if already cached
    manager = get_duckdb_manager()
    if manager.has_cached(request.attachment_id):
        logger.info(
            "DuckDB already cached for attachment %d, reusing", request.attachment_id
        )
        # Return cached info by re-querying schema
        schema = _query_service.get_schema(request.attachment_id)
        return RemoteDataGenerateResponse(
            success=True,
            attachment_id=request.attachment_id,
            duckdb_attachment_id=None,
            summary={"tables": schema.get("tables", [])},
            tables=[
                {"name": t["name"], "rows": t["rows"]}
                for t in schema.get("tables", [])
            ],
            generation_time_ms=0,
            error=None,
        )

    # Fetch source file binary data
    try:
        binary_data, source_file, file_extension = await _content_fetcher.fetch(
            request.content_ref
        )
    except Exception as e:
        logger.error(
            "Failed to fetch content for attachment %d: %s",
            request.attachment_id,
            e,
        )
        return RemoteDataGenerateResponse(
            success=False,
            attachment_id=request.attachment_id,
            error=f"Failed to fetch content: {e}",
        )

    # Generate DuckDB
    result = await _generator.generate(
        attachment_id=request.attachment_id,
        binary_data=binary_data,
        source_file=source_file,
        file_extension=file_extension,
    )

    if result["success"]:
        # Upload .duckdb file to Backend
        duckdb_path = manager.get_duckdb_path(request.attachment_id)
        if duckdb_path.exists():
            duckdb_binary = duckdb_path.read_bytes()
            uploader = get_artifact_uploader()
            duckdb_attachment_id = await uploader.upload_duckdb_artifact(
                attachment_id=request.attachment_id,
                duckdb_binary_data=duckdb_binary,
            )
            result["duckdb_attachment_id"] = duckdb_attachment_id

    return RemoteDataGenerateResponse(**result)


@router.post("/query", response_model=RemoteDataQueryResponse)
async def query_duckdb(
    request: RemoteDataQueryRequest,
) -> Any:
    """Execute a SQL query against an attachment's DuckDB file.

    The query runs in :memory: + ATTACH read-only mode with
    temporary table support. Use data_db. prefix for table names.

    Args:
        request: The query request with attachment_id and sql.

    Returns:
        RemoteDataQueryResponse with query results.
    """
    logger.info(
        "Querying DuckDB for attachment %d, SQL: %s",
        request.attachment_id,
        request.sql[:200],
    )

    # Run query in thread to avoid blocking event loop
    result = await asyncio.to_thread(
        _query_service.execute_query,
        attachment_id=request.attachment_id,
        sql=request.sql,
    )

    return RemoteDataQueryResponse(**result)


@router.get("/schema/{attachment_id}", response_model=RemoteDataSchemaResponse)
async def get_data_schema(
    attachment_id: int,
) -> Any:
    """Get the table schema for an attachment's DuckDB file.

    Returns table names, column names, types, null counts, and row counts.
    Table names include the data_db. prefix for use in SQL queries.

    Args:
        attachment_id: The attachment ID to inspect.

    Returns:
        RemoteDataSchemaResponse with schema information.
    """
    logger.info("Getting schema for attachment %d", attachment_id)

    result = await asyncio.to_thread(
        _query_service.get_schema,
        attachment_id=attachment_id,
    )

    return RemoteDataSchemaResponse(**result)
