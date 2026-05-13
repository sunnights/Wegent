# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""DuckDB query execution service shared across Wegent modules.

Executes SQL queries against cached .duckdb files downloaded from Backend.
Used by both the Executor (ClaudeCode shell) and Chat Shell to provide
equivalent data analysis capabilities over knowledge-base generated
.duckdb artifacts.

Security is enforced at the connection level, not via SQL keyword blocking:

1. ATTACH with READ_ONLY: Prevents all write operations (DROP, DELETE, INSERT, etc.)
2. enable_external_access = false: Blocks file/network access (read_csv_auto, etc.)

These connection-level restrictions make SQL-level keyword filtering redundant.

The cache directory is injected via the constructor so the caller controls
lifecycle/placement:

- Executor uses container-local cache (destroyed when task container exits).
- Chat Shell uses per-task subdirectories under a process-level base dir,
  cleaned up on task completion or process shutdown.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

import duckdb
import httpx

logger = logging.getLogger(__name__)

# Default cache directory used by callers that do not override it
DEFAULT_CACHE_DIR = "/tmp/wegent_duckdb_cache"

# Default query-side limits (kept identical to the original Executor impl so
# Chat Shell and Executor return equivalent results)
DEFAULT_MAX_ROWS = 5000
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 120.0

# Type alias: a ContentRef-like dict with `url` and optional `auth_token`
ContentRefLike = dict[str, Any]

# Callable type for customizing HTTP download (e.g. to plug in internal-token
# auth, tracing, or a mock in tests).
#
# Signature: async def downloader(url: str, headers: dict[str, str]) -> bytes
Downloader = Callable[[str, dict[str, str]], "Any"]


class DuckDBQueryExecutor:
    """Execute SQL queries against cached .duckdb files.

    Cache lifecycle is delegated to the caller (by injecting ``cache_dir``).
    No LRU/TTL is implemented here — callers either destroy the cache directory
    with the owning container/task or manage pruning out-of-band.

    Security is enforced at the DuckDB connection level:

    - ATTACH with READ_ONLY prevents all write operations
    - enable_external_access=false blocks file/network access

    The optional ``downloader`` hook lets callers swap out HTTP transport
    (e.g. for unit tests or to reuse an existing ``httpx.AsyncClient`` with
    custom headers). If not provided, a short-lived ``httpx.AsyncClient`` is
    created per download.
    """

    def __init__(
        self,
        cache_dir: str | Path = DEFAULT_CACHE_DIR,
        *,
        download_timeout: float = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
        downloader: Optional[Downloader] = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._download_timeout = download_timeout
        self._downloader = downloader

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def get_cache_path(self, attachment_id: int) -> Path:
        """Get local cache path for an attachment.

        Args:
            attachment_id: The attachment ID of the .duckdb file.

        Returns:
            Path to the local cached .duckdb file.
        """
        key = hashlib.sha256(f"attachment_{attachment_id}".encode()).hexdigest()
        return self.cache_dir / f"{key}.duckdb"

    async def ensure_cached(
        self,
        attachment_id: int,
        content_ref: ContentRefLike,
    ) -> Path:
        """Download .duckdb file if not cached.

        Args:
            attachment_id: The attachment ID of the .duckdb file.
            content_ref: Content reference with url and (optional) auth_token.

        Returns:
            Path to the cached .duckdb file.

        Raises:
            httpx.HTTPError: If downloading fails.
            RuntimeError: If downloaded data is not a valid DuckDB file.
        """
        cache_path = self.get_cache_path(attachment_id)

        if cache_path.exists():
            logger.debug("Cache hit for duckdb attachment_id=%d", attachment_id)
            return cache_path

        logger.info("Downloading .duckdb file for attachment_id=%d", attachment_id)

        url = content_ref.get("url", "")
        auth_token = content_ref.get("auth_token", "")
        headers: dict[str, str] = {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        if self._downloader is not None:
            data = await self._downloader(url, headers)
        else:
            async with httpx.AsyncClient(timeout=self._download_timeout) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.content

        if not self._is_valid_duckdb_data(data):
            raise RuntimeError(
                f"Downloaded data for attachment_id={attachment_id} "
                f"does not appear to be a valid DuckDB file"
            )

        cache_path.write_bytes(data)
        logger.info(
            "Cached .duckdb file for attachment_id=%d (size=%.1f KB)",
            attachment_id,
            len(data) / 1024,
        )

        return cache_path

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    def execute_query(
        self,
        duckdb_path: Path,
        sql: str,
        max_rows: int = DEFAULT_MAX_ROWS,
    ) -> dict[str, Any]:
        """Execute SQL query in read-only mode.

        Uses an in-memory DuckDB connection with ATTACH READ_ONLY for safe
        execution. After ATTACH, disables external access to prevent
        further filesystem reads via DuckDB scan functions.

        Args:
            duckdb_path: Local path to the .duckdb file.
            sql: SQL query to execute.
            max_rows: Maximum number of rows to return.

        Returns:
            Dict with columns, rows, row_count, truncated, and optionally error.
        """
        safe_path = str(duckdb_path).replace("'", "\\'")

        conn = duckdb.connect(":memory:")
        try:
            conn.execute(f"ATTACH '{safe_path}' AS data_db (READ_ONLY)")
            conn.execute("SET enable_external_access = false")

            start_time = time.monotonic()

            result = conn.execute(sql)

            columns = (
                [desc[0] for desc in result.description] if result.description else []
            )

            all_rows = result.fetchall()

            execution_time_ms = (time.monotonic() - start_time) * 1000

            truncated = len(all_rows) > max_rows
            limited_rows = all_rows[:max_rows]

            rows: list[list[Any]] = []
            for row in limited_rows:
                serialized_row = []
                for val in row:
                    if val is not None and not isinstance(val, (str, int, float, bool)):
                        val = str(val)
                    serialized_row.append(val)
                rows.append(serialized_row)

            total_count: int | None = None
            if truncated:
                total_count = len(all_rows)

            return {
                "success": True,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "total_count": total_count,
                "execution_time_ms": round(execution_time_ms, 2),
                "truncated": truncated,
            }

        except (duckdb.IOException, duckdb.OperationalError) as exc:
            logger.warning("Query timed out: %s", sql[:100])
            return {
                "success": False,
                "error": f"Query timed out: {exc}",
            }
        except Exception as exc:
            logger.error("Query execution failed: %s", exc)
            return {
                "success": False,
                "error": str(exc),
            }
        finally:
            conn.close()

    def get_schema(self, duckdb_path: Path) -> dict[str, Any]:
        """Extract schema information from a DuckDB file.

        Args:
            duckdb_path: Local path to the .duckdb file.

        Returns:
            Dict with tables list containing name, row_count, and columns,
            or error if extraction fails.
        """
        safe_path = str(duckdb_path).replace("'", "\\'")

        conn = duckdb.connect(":memory:")
        try:
            conn.execute(f"ATTACH '{safe_path}' AS data_db (READ_ONLY)")
            conn.execute("SET enable_external_access = false")

            tables_result = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_catalog = 'data_db' AND table_schema = 'main'"
            ).fetchall()

            tables: list[dict[str, Any]] = []

            for (table_name,) in tables_result:
                try:
                    count_result = conn.execute(
                        f'SELECT COUNT(*) FROM data_db."{table_name}"'
                    ).fetchone()
                    row_count = count_result[0] if count_result else 0

                    columns: list[dict[str, Any]] = []
                    col_result = conn.execute(
                        "SELECT column_name, data_type "
                        "FROM information_schema.columns "
                        "WHERE table_catalog = 'data_db' "
                        "AND table_name = ? "
                        "AND table_schema = 'main' "
                        "ORDER BY ordinal_position",
                        [table_name],
                    ).fetchall()

                    for col_name, col_type in col_result:
                        try:
                            null_result = conn.execute(
                                f'SELECT COUNT(*) FROM data_db."{table_name}" '
                                f'WHERE "{col_name}" IS NULL'
                            ).fetchone()
                            null_count = null_result[0] if null_result else 0
                        except Exception:
                            null_count = 0

                        columns.append(
                            {
                                "name": col_name,
                                "type": col_type,
                                "null_count": null_count,
                            }
                        )

                    tables.append(
                        {
                            "name": table_name,
                            "row_count": row_count,
                            "columns": columns,
                        }
                    )

                except Exception as exc:
                    logger.warning(
                        "Failed to extract schema for table '%s': %s",
                        table_name,
                        exc,
                    )

            return {
                "success": True,
                "tables": tables,
            }

        except Exception as exc:
            logger.error("Schema extraction failed: %s", exc)
            return {
                "success": False,
                "error": str(exc),
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _is_valid_duckdb_data(self, data: bytes) -> bool:
        """Check if data appears to be a valid DuckDB file.

        Tries to open the data with DuckDB and execute a simple query.
        This is an expensive check (writes a temp file), but cheap compared
        to caching bogus data that would fail later.

        Args:
            data: Binary data to check.

        Returns:
            True if the data appears to be a valid DuckDB file.
        """
        if len(data) < 4096:
            return False

        try:
            with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=True) as tmp:
                tmp.write(data)
                tmp.flush()

                conn = duckdb.connect(tmp.name, read_only=True)
                try:
                    conn.execute("SELECT 1").fetchone()
                    return True
                finally:
                    conn.close()
        except Exception:
            return False


__all__ = [
    "DuckDBQueryExecutor",
    "DEFAULT_CACHE_DIR",
    "DEFAULT_MAX_ROWS",
    "ContentRefLike",
    "Downloader",
]
