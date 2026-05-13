# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Task-scoped DuckDB query runner for Chat Shell.

Although the class name still carries the historical ``sandbox`` suffix (kept
for consistency with the original design doc), the runner executes queries
**in-process** inside Chat Shell rather than inside an external container.

Rationale for in-process execution:

- Chat Shell's ``SandboxClient`` only accepts text prompts; it has no
  ``upload_file`` / ``execute_code`` primitives, so remote execution would
  require wrapping every query in a Claude-Code-driven prompt — slow and
  fragile.
- The security guarantees we care about (no writes, no arbitrary filesystem
  access, no external network from SQL) are enforced by DuckDB itself at the
  connection level (``ATTACH ... (READ_ONLY)`` + ``SET enable_external_access
  = false``). These hold regardless of whether DuckDB runs inside a container
  or inside Chat Shell's process.
- Execution is faster and avoids an extra round-trip through executor_manager.

Task-scoped state
-----------------

Downloaded ``.duckdb`` files are cached per ``task_id`` under
``{DUCKDB_CACHE_DIR}/task_{task_id}/``. The :class:`ChatShellDuckDBRunner`
tracks in-memory which ``(task_id, attachment_id)`` pairs have already been
cached so repeated queries within a task skip the download entirely.

The cache directory for a task can be reclaimed by calling
:meth:`ChatShellDuckDBRunner.cleanup_task` when the task terminates.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from shared.services.duckdb_query import DuckDBQueryExecutor

logger = logging.getLogger(__name__)


class ChatShellDuckDBRunner:
    """Execute DuckDB queries in-process on behalf of Chat Shell tasks.

    Instances are intended to be singletons at the Chat Shell process level;
    see :func:`get_shared_duckdb_runner` for the accessor.

    Thread-safety: all public methods are ``async`` and use an ``asyncio.Lock``
    to serialize cache-preparation for the same ``(task_id, attachment_id)``
    pair. Query execution itself is run in a worker thread
    (``asyncio.to_thread``) since the DuckDB Python SDK is synchronous.
    """

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        query_timeout: float = 60.0,
        max_rows: int = 5000,
    ) -> None:
        self._cache_base_dir = Path(cache_dir)
        self._cache_base_dir.mkdir(parents=True, exist_ok=True)
        self._query_timeout = query_timeout
        self._max_rows = max_rows

        # Executors are keyed by task_id so caches don't bleed between tasks.
        self._executors: dict[int, DuckDBQueryExecutor] = {}
        # Track attachments we've already cached per task to skip re-downloads.
        self._cached: dict[int, set[int]] = {}
        # Guard concurrent cache preparation for the same task/attachment pair.
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_query(
        self,
        *,
        task_id: int,
        attachment_id: int,
        content_ref: dict[str, Any],
        sql: str,
        max_rows: Optional[int] = None,
    ) -> dict[str, Any]:
        """Download (if needed) and execute ``sql`` against an attachment.

        Args:
            task_id: The chat task ID — used for cache scoping.
            attachment_id: The Backend-provided attachment ID for the
                ``.duckdb`` file.
            content_ref: A ContentRef-like dict (``url`` + ``auth_token``)
                pointing at the downloadable ``.duckdb`` file.
            sql: The SQL statement to execute.
            max_rows: Optional per-call override of the default row cap.

        Returns:
            A dict matching the shape returned by
            :meth:`DuckDBQueryExecutor.execute_query`.
        """
        effective_max_rows = max_rows or self._max_rows

        try:
            duckdb_path = await self._ensure_cached(
                task_id=task_id,
                attachment_id=attachment_id,
                content_ref=content_ref,
            )
        except Exception as exc:
            logger.exception(
                "DuckDB cache preparation failed task_id=%s attachment_id=%s: %s",
                task_id,
                attachment_id,
                exc,
            )
            return {
                "success": False,
                "error": f"Failed to prepare .duckdb cache: {exc}",
            }

        executor = self._get_executor(task_id)

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    executor.execute_query,
                    duckdb_path,
                    sql,
                    effective_max_rows,
                ),
                timeout=self._query_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "DuckDB query timed out task_id=%s attachment_id=%s timeout=%.1fs",
                task_id,
                attachment_id,
                self._query_timeout,
            )
            return {
                "success": False,
                "error": f"Query timed out after {self._query_timeout:.1f}s",
            }

    async def run_schema(
        self,
        *,
        task_id: int,
        attachment_id: int,
        content_ref: dict[str, Any],
    ) -> dict[str, Any]:
        """Download (if needed) and extract schema info for an attachment."""
        try:
            duckdb_path = await self._ensure_cached(
                task_id=task_id,
                attachment_id=attachment_id,
                content_ref=content_ref,
            )
        except Exception as exc:
            logger.exception(
                "DuckDB cache preparation failed task_id=%s attachment_id=%s: %s",
                task_id,
                attachment_id,
                exc,
            )
            return {
                "success": False,
                "error": f"Failed to prepare .duckdb cache: {exc}",
            }

        executor = self._get_executor(task_id)

        return await asyncio.to_thread(executor.get_schema, duckdb_path)

    async def cleanup_task(self, task_id: int) -> None:
        """Remove on-disk cache + in-memory state for a finished task."""
        async with self._lock:
            self._executors.pop(task_id, None)
            self._cached.pop(task_id, None)

        task_dir = self._task_cache_dir(task_id)
        if task_dir.exists():
            try:
                await asyncio.to_thread(shutil.rmtree, task_dir, True)
            except Exception as exc:
                logger.warning(
                    "Failed to remove duckdb cache dir %s: %s", task_dir, exc
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _task_cache_dir(self, task_id: int) -> Path:
        return self._cache_base_dir / f"task_{task_id}"

    def _get_executor(self, task_id: int) -> DuckDBQueryExecutor:
        executor = self._executors.get(task_id)
        if executor is None:
            executor = DuckDBQueryExecutor(cache_dir=self._task_cache_dir(task_id))
            self._executors[task_id] = executor
            self._cached.setdefault(task_id, set())
        return executor

    async def _ensure_cached(
        self,
        *,
        task_id: int,
        attachment_id: int,
        content_ref: dict[str, Any],
    ) -> Path:
        async with self._lock:
            executor = self._get_executor(task_id)
            already = self._cached.setdefault(task_id, set())
            if (
                attachment_id in already
                and executor.get_cache_path(attachment_id).exists()
            ):
                return executor.get_cache_path(attachment_id)

        path = await executor.ensure_cached(
            attachment_id=attachment_id,
            content_ref=content_ref,
        )

        async with self._lock:
            self._cached.setdefault(task_id, set()).add(attachment_id)

        return path


# ------------------------------------------------------------------
# Process-level singleton accessor
# ------------------------------------------------------------------

_shared_runner: Optional[ChatShellDuckDBRunner] = None
_shared_runner_lock = asyncio.Lock()


async def get_shared_duckdb_runner() -> ChatShellDuckDBRunner:
    """Return the process-wide :class:`ChatShellDuckDBRunner` singleton.

    The singleton is built lazily to avoid touching Pydantic settings at
    module import time (simplifies testing and cold-import behaviour).
    """
    global _shared_runner
    if _shared_runner is not None:
        return _shared_runner

    async with _shared_runner_lock:
        if _shared_runner is None:
            # Import inside the function so tests can patch settings
            # without worrying about import order.
            from chat_shell.core.config import settings

            _shared_runner = ChatShellDuckDBRunner(
                cache_dir=settings.DUCKDB_CACHE_DIR,
                query_timeout=settings.DUCKDB_QUERY_TIMEOUT,
                max_rows=settings.DUCKDB_MAX_ROWS,
            )
    return _shared_runner


def reset_shared_duckdb_runner() -> None:
    """Reset the module-level singleton (test helper)."""
    global _shared_runner
    _shared_runner = None


__all__ = [
    "ChatShellDuckDBRunner",
    "get_shared_duckdb_runner",
    "reset_shared_duckdb_runner",
]
