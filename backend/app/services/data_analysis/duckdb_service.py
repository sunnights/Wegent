# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""DuckDB data analysis service for Backend.

Orchestrates DuckDB generation and querying by delegating to
knowledge_runtime. Manages the duckdb_cache table and integrates
with ContextService for AI context injection.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.duckdb_cache import DuckDBCache

logger = logging.getLogger(__name__)

# File extensions that support DuckDB data analysis
DUCKDB_SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".tsv"}


class DuckDBDataService:
    """Service for managing DuckDB data analysis lifecycle."""

    def is_supported_extension(self, extension: str) -> bool:
        """Check if a file extension is supported for DuckDB analysis."""
        return extension.lower() in DUCKDB_SUPPORTED_EXTENSIONS

    def get_duckdb_cache(
        self, db: Session, attachment_id: int
    ) -> Optional[DuckDBCache]:
        """Get DuckDB cache entry for an attachment.

        Args:
            db: Database session.
            attachment_id: The original attachment ID.

        Returns:
            DuckDBCache record if found, None otherwise.
        """
        return (
            db.query(DuckDBCache)
            .filter(DuckDBCache.attachment_id == attachment_id)
            .first()
        )

    def create_cache_entry(
        self,
        db: Session,
        attachment_id: int,
        status: str = "generating",
    ) -> DuckDBCache:
        """Create a new DuckDB cache entry with generating status.

        Args:
            db: Database session.
            attachment_id: The original attachment ID.
            status: Initial status (default: "generating").

        Returns:
            The created DuckDBCache record.
        """
        cache = DuckDBCache(
            attachment_id=attachment_id,
            duckdb_attachment_id=0,  # Placeholder, updated after upload
            status=status,
        )
        db.add(cache)
        db.flush()
        return cache

    def update_cache_entry(
        self,
        db: Session,
        attachment_id: int,
        duckdb_attachment_id: Optional[int] = None,
        summary: Optional[dict] = None,
        tables_count: int = 0,
        file_size: int = 0,
        source_file_hash: Optional[str] = None,
        status: str = "ready",
    ) -> Optional[DuckDBCache]:
        """Update a DuckDB cache entry with generation results.

        Args:
            db: Database session.
            attachment_id: The original attachment ID.
            duckdb_attachment_id: The .duckdb file attachment ID.
            summary: SUMMARIZE results + sample data.
            tables_count: Number of tables.
            file_size: DuckDB file size in bytes.
            source_file_hash: SHA256 of the source file.
            status: New status.

        Returns:
            Updated DuckDBCache record, or None if not found.
        """
        cache = self.get_duckdb_cache(db, attachment_id)
        if cache is None:
            return None

        if duckdb_attachment_id is not None:
            cache.duckdb_attachment_id = duckdb_attachment_id
        if summary is not None:
            cache.summary = summary
        if tables_count > 0:
            cache.tables_count = tables_count
        if file_size > 0:
            cache.file_size = file_size
        if source_file_hash is not None:
            cache.source_file_hash = source_file_hash
        cache.status = status

        db.flush()
        return cache

    async def generate_duckdb(
        self,
        db: Session,
        attachment_id: int,
        binary_data: bytes,
        filename: str,
        file_extension: str,
        user_id: int,
    ) -> Optional[DuckDBCache]:
        """Generate a DuckDB file for an Excel/CSV attachment.

        Calls knowledge_runtime's /internal/data/generate endpoint,
        then updates the duckdb_cache table with the results.

        Args:
            db: Database session.
            attachment_id: The attachment ID.
            binary_data: Raw binary data of the source file.
            filename: Original filename.
            file_extension: File extension.
            user_id: User ID who owns the attachment.

        Returns:
            Updated DuckDBCache record, or None on failure.
        """
        # Check if already cached
        existing = self.get_duckdb_cache(db, attachment_id)
        if existing and existing.status == "ready":
            source_hash = hashlib.sha256(binary_data).hexdigest()
            if existing.source_file_hash == source_hash:
                logger.info(
                    "DuckDB already cached and valid for attachment %d",
                    attachment_id,
                )
                return existing

        # Create or reset cache entry
        if existing:
            existing.status = "generating"
            db.flush()
            cache = existing
        else:
            cache = self.create_cache_entry(db, attachment_id)

        try:
            result = await self._call_knowledge_runtime_generate(
                attachment_id=attachment_id,
                binary_data=binary_data,
                filename=filename,
                file_extension=file_extension,
                user_id=user_id,
            )

            if result and result.get("success"):
                self.update_cache_entry(
                    db=db,
                    attachment_id=attachment_id,
                    duckdb_attachment_id=result.get("duckdb_attachment_id"),
                    summary=result.get("summary"),
                    tables_count=len(result.get("tables", [])),
                    source_file_hash=hashlib.sha256(binary_data).hexdigest(),
                    status="ready",
                )
                logger.info(
                    "DuckDB generated successfully for attachment %d",
                    attachment_id,
                )
            else:
                error_msg = result.get("error", "Unknown error") if result else "No response"
                self.update_cache_entry(
                    db=db,
                    attachment_id=attachment_id,
                    status="failed",
                )
                logger.warning(
                    "DuckDB generation failed for attachment %d: %s",
                    attachment_id,
                    error_msg,
                )

        except Exception as e:
            self.update_cache_entry(
                db=db,
                attachment_id=attachment_id,
                status="failed",
            )
            logger.error(
                "DuckDB generation exception for attachment %d: %s",
                attachment_id,
                e,
            )

        db.flush()
        return self.get_duckdb_cache(db, attachment_id)

    async def _call_knowledge_runtime_generate(
        self,
        attachment_id: int,
        binary_data: bytes,
        filename: str,
        file_extension: str,
        user_id: int,
    ) -> Optional[dict[str, Any]]:
        """Call knowledge_runtime's /internal/data/generate endpoint.

        Args:
            attachment_id: The attachment ID.
            binary_data: Raw binary data of the source file.
            filename: Original filename.
            file_extension: File extension.
            user_id: User ID.

        Returns:
            Response dict from knowledge_runtime, or None on failure.
        """
        kr_url = settings.KNOWLEDGE_RUNTIME_URL
        internal_token = settings.INTERNAL_SERVICE_TOKEN

        # Build content_ref for knowledge_runtime to fetch the file
        # Use Backend attachment stream URL
        backend_url = settings.BACKEND_INTERNAL_URL.rstrip("/")
        api_prefix = settings.API_PREFIX or ""
        stream_url = f"{backend_url}{api_prefix}/api/internal/rag/content/{attachment_id}"

        # Generate a download token for the attachment
        try:
            from app.services.auth.rag_download_token import generate_rag_download_token

            download_token = generate_rag_download_token(attachment_id)
        except Exception:
            download_token = internal_token

        payload = {
            "attachment_id": attachment_id,
            "content_ref": {
                "kind": "backend_attachment_stream",
                "url": stream_url,
                "auth_token": download_token,
            },
        }

        headers = {"Content-Type": "application/json"}
        if internal_token:
            headers["Authorization"] = f"Bearer {internal_token}"

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{kr_url}/internal/data/generate",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(
                "knowledge_runtime generate HTTP error for attachment %d: %d - %s",
                attachment_id,
                e.response.status_code,
                e.response.text[:200],
            )
            return None
        except Exception as e:
            logger.error(
                "knowledge_runtime generate error for attachment %d: %s",
                attachment_id,
                e,
            )
            return None

    async def query_duckdb(
        self,
        db: Session,
        attachment_id: int,
        sql: str,
    ) -> dict[str, Any]:
        """Execute a SQL query against an attachment's DuckDB file.

        Delegates to knowledge_runtime's /internal/data/query endpoint.

        Args:
            db: Database session.
            attachment_id: The attachment ID to query.
            sql: SQL query to execute.

        Returns:
            Query result dict from knowledge_runtime.
        """
        kr_url = settings.KNOWLEDGE_RUNTIME_URL
        internal_token = settings.INTERNAL_SERVICE_TOKEN

        payload = {
            "task_id": 0,  # Task ID not needed for direct queries
            "attachment_id": attachment_id,
            "sql": sql,
        }

        headers = {"Content-Type": "application/json"}
        if internal_token:
            headers["Authorization"] = f"Bearer {internal_token}"

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{kr_url}/internal/data/query",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(
                "knowledge_runtime query HTTP error for attachment %d: %d",
                attachment_id,
                e.response.status_code,
            )
            return {
                "success": False,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "error": f"knowledge_runtime query failed: HTTP {e.response.status_code}",
            }
        except Exception as e:
            logger.error(
                "knowledge_runtime query error for attachment %d: %s",
                attachment_id,
                e,
            )
            return {
                "success": False,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "error": f"knowledge_runtime query failed: {e}",
            }

    async def get_schema(
        self,
        db: Session,
        attachment_id: int,
    ) -> dict[str, Any]:
        """Get the table schema for an attachment's DuckDB file.

        Delegates to knowledge_runtime's /internal/data/schema endpoint.

        Args:
            db: Database session.
            attachment_id: The attachment ID.

        Returns:
            Schema result dict from knowledge_runtime.
        """
        kr_url = settings.KNOWLEDGE_RUNTIME_URL
        internal_token = settings.INTERNAL_SERVICE_TOKEN

        headers = {}
        if internal_token:
            headers["Authorization"] = f"Bearer {internal_token}"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"{kr_url}/internal/data/schema/{attachment_id}",
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(
                "knowledge_runtime schema HTTP error for attachment %d: %d",
                attachment_id,
                e.response.status_code,
            )
            return {
                "attachment_id": attachment_id,
                "tables": [],
                "error": f"knowledge_runtime schema failed: HTTP {e.response.status_code}",
            }
        except Exception as e:
            logger.error(
                "knowledge_runtime schema error for attachment %d: %s",
                attachment_id,
                e,
            )
            return {
                "attachment_id": attachment_id,
                "tables": [],
                "error": f"knowledge_runtime schema failed: {e}",
            }

    def build_extracted_text_from_summary(
        self,
        summary: dict[str, Any],
        filename: str,
    ) -> str:
        """Build extracted_text content from DuckDB summary for AI context.

        Replaces the ExcelTruncationStrategy output with structured
        SUMMARIZE data and sample rows.

        Args:
            summary: The summary dict from DuckDB generation.
            filename: Original filename.

        Returns:
            Formatted markdown text for AI context injection.
        """
        lines = [f"## Data Summary: {filename}", ""]

        tables = summary.get("tables", [])
        for table in tables:
            table_name = table.get("name", "unknown")
            row_count = table.get("row_count", 0)
            lines.append(f"### Table: {table_name} ({row_count:,} rows)")
            lines.append("")

            # Format column summary as markdown table
            columns = table.get("columns", [])
            if columns:
                lines.append(
                    "| Column | Type | Min | Max | Unique | Avg | Null% |"
                )
                lines.append(
                    "|--------|------|-----|-----|--------|-----|-------|"
                )
                for col in columns:
                    col_name = col.get("column_name", "")
                    col_type = col.get("column_type", "")
                    min_val = col.get("min") or "-"
                    max_val = col.get("max") or "-"
                    unique = col.get("unique")
                    unique_str = str(unique) if unique is not None else "-"
                    avg = col.get("avg")
                    avg_str = f"{avg:.2f}" if avg is not None else "-"
                    null_pct = col.get("null_percentage")
                    null_str = f"{null_pct:.1f}%" if null_pct is not None else "-"

                    lines.append(
                        f"| {col_name} | {col_type} | {min_val} | {max_val} "
                        f"| {unique_str} | {avg_str} | {null_str} |"
                    )
                lines.append("")

        lines.append(
            "> Use wegent_data_schema to get full table structure, "
            "wegent_data_query to execute SQL queries for detailed analysis."
        )

        return "\n".join(lines)


# Module-level singleton
duckdb_data_service = DuckDBDataService()
