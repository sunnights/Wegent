# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Thin compatibility shim that re-exports the shared DuckDB query service.

The original implementation lived here; it has been promoted to
``shared.services.duckdb_query`` so that both the Executor and the Chat Shell
can reuse a single canonical implementation. This module preserves the
existing import path (``executor.services.duckdb_query.DuckDBQueryExecutor``)
for backwards compatibility with existing executor callers and tests.

New code should import directly from ``shared.services.duckdb_query``.
"""

from __future__ import annotations

from shared.services.duckdb_query import (
    DEFAULT_CACHE_DIR,
    DEFAULT_MAX_ROWS,
    ContentRefLike,
    DuckDBQueryExecutor,
)

__all__ = [
    "DuckDBQueryExecutor",
    "DEFAULT_CACHE_DIR",
    "DEFAULT_MAX_ROWS",
    "ContentRefLike",
]
