# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the Chat Shell DuckDB runner."""

from __future__ import annotations

from unittest.mock import patch

import duckdb
import pytest

from chat_shell.services.duckdb_sandbox_runner import ChatShellDuckDBRunner


@pytest.fixture
def sample_duckdb_bytes(tmp_path):
    """Create a small duckdb file and return its bytes."""
    db_path = tmp_path / "sample.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE TABLE sales (id INTEGER, name VARCHAR, amount DOUBLE)")
    conn.execute("INSERT INTO sales VALUES (1, 'Alice', 100.0), (2, 'Bob', 200.0)")
    conn.execute("CHECKPOINT")
    conn.close()
    return db_path.read_bytes()


@pytest.fixture
def runner(tmp_path):
    """Build a runner pointing at a tmp cache dir."""
    return ChatShellDuckDBRunner(
        cache_dir=tmp_path / "duckdb_runner_cache",
        query_timeout=30.0,
        max_rows=100,
    )


class TestCacheScoping:
    @pytest.mark.asyncio
    async def test_run_query_returns_results(self, runner, sample_duckdb_bytes) -> None:
        """Primary happy-path: run a SELECT and get rows back."""

        async def _downloader(url, headers):
            return sample_duckdb_bytes

        with patch.object(runner, "_get_executor", wraps=runner._get_executor) as spy:
            # Override the executor's downloader via a direct patch on the
            # shared DuckDBQueryExecutor httpx client. We use the public
            # ``downloader`` injection point instead of monkey-patching.
            executor = runner._get_executor(task_id=42)
            executor._downloader = _downloader  # type: ignore[attr-defined]

            result = await runner.run_query(
                task_id=42,
                attachment_id=99,
                content_ref={"url": "http://backend/file", "auth_token": "tok"},
                sql="SELECT * FROM data_db.sales ORDER BY id",
            )

        assert result["success"] is True
        assert result["columns"] == ["id", "name", "amount"]
        assert result["row_count"] == 2

    @pytest.mark.asyncio
    async def test_run_query_caches_per_task(self, runner, sample_duckdb_bytes) -> None:
        """A second call with the same attachment should reuse the cache."""
        call_count = {"n": 0}

        async def _downloader(url, headers):
            call_count["n"] += 1
            return sample_duckdb_bytes

        executor = runner._get_executor(task_id=7)
        executor._downloader = _downloader  # type: ignore[attr-defined]

        for _ in range(2):
            await runner.run_query(
                task_id=7,
                attachment_id=11,
                content_ref={"url": "http://backend/file"},
                sql="SELECT COUNT(*) FROM data_db.sales",
            )

        assert call_count["n"] == 1

    @pytest.mark.asyncio
    async def test_different_tasks_use_isolated_caches(
        self, runner, sample_duckdb_bytes
    ) -> None:
        """Different task IDs must not share cache files."""

        async def _downloader(url, headers):
            return sample_duckdb_bytes

        for task_id in (1, 2):
            executor = runner._get_executor(task_id=task_id)
            executor._downloader = _downloader  # type: ignore[attr-defined]
            await runner.run_query(
                task_id=task_id,
                attachment_id=42,
                content_ref={"url": "http://backend/file"},
                sql="SELECT 1",
            )

        path_1 = runner._get_executor(1).get_cache_path(42)
        path_2 = runner._get_executor(2).get_cache_path(42)
        assert path_1 != path_2
        assert path_1.exists()
        assert path_2.exists()

    @pytest.mark.asyncio
    async def test_cleanup_task_removes_cache(
        self, runner, sample_duckdb_bytes
    ) -> None:
        """cleanup_task must wipe the on-disk cache dir."""

        async def _downloader(url, headers):
            return sample_duckdb_bytes

        executor = runner._get_executor(task_id=33)
        executor._downloader = _downloader  # type: ignore[attr-defined]
        await runner.run_query(
            task_id=33,
            attachment_id=1,
            content_ref={"url": "http://backend/file"},
            sql="SELECT 1",
        )

        task_dir = runner._task_cache_dir(33)
        assert task_dir.exists()

        await runner.cleanup_task(33)

        assert not task_dir.exists()
        assert 33 not in runner._executors


class TestRunQueryErrors:
    @pytest.mark.asyncio
    async def test_download_failure_returns_error(self, runner) -> None:
        """If download throws, run_query returns a structured error."""

        async def _downloader(url, headers):
            raise RuntimeError("boom")

        executor = runner._get_executor(task_id=1)
        executor._downloader = _downloader  # type: ignore[attr-defined]

        result = await runner.run_query(
            task_id=1,
            attachment_id=1,
            content_ref={"url": "http://bad"},
            sql="SELECT 1",
        )

        assert result["success"] is False
        assert "Failed to prepare" in result["error"]

    @pytest.mark.asyncio
    async def test_readonly_rejects_writes(self, runner, sample_duckdb_bytes) -> None:
        """Writes must be rejected by the READ_ONLY ATTACH."""

        async def _downloader(url, headers):
            return sample_duckdb_bytes

        executor = runner._get_executor(task_id=1)
        executor._downloader = _downloader  # type: ignore[attr-defined]

        result = await runner.run_query(
            task_id=1,
            attachment_id=1,
            content_ref={"url": "http://backend/file"},
            sql="DROP TABLE data_db.sales",
        )

        assert result["success"] is False
