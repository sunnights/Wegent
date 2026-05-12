# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for DuckDB query service."""

import pytest

from knowledge_runtime.config import reset_settings
from knowledge_runtime.services.duckdb_query import DuckDBQueryService, _has_limit_clause


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset settings before each test."""
    reset_settings()
    yield
    reset_settings()


class TestHasLimitClause:
    """Tests for SQL LIMIT clause detection."""

    def test_select_with_limit(self):
        assert _has_limit_clause("SELECT * FROM t LIMIT 10") is True

    def test_select_without_limit(self):
        assert _has_limit_clause("SELECT * FROM t") is False

    def test_complex_query_with_limit(self):
        assert _has_limit_clause(
            "SELECT * FROM data_db.sales WHERE amount > 100 LIMIT 50"
        ) is True


class TestDuckDBQueryService:
    """Tests for DuckDBQueryService."""

    def test_execute_query_non_select(self, tmp_path):
        """Non-SELECT queries are rejected."""
        with patch(
            "knowledge_runtime.services.duckdb_query.get_settings"
        ) as mock_settings:
            settings = mock_settings.return_value
            settings.duckdb_cache_dir = str(tmp_path)
            settings.duckdb_cache_max_size_gb = 5
            settings.duckdb_cache_ttl_hours = 24
            settings.duckdb_max_query_rows = 5000
            settings.duckdb_query_timeout = 30

            service = DuckDBQueryService()
            result = service.execute_query(
                attachment_id=1,
                sql="DROP TABLE data_db.sales",
            )
            assert result["success"] is False
            assert "SELECT" in result["error"]

    def test_execute_query_no_cache(self, tmp_path):
        """Query returns error when no cached file exists."""
        with patch(
            "knowledge_runtime.services.duckdb_query.get_settings"
        ) as mock_settings:
            settings = mock_settings.return_value
            settings.duckdb_cache_dir = str(tmp_path)
            settings.duckdb_cache_max_size_gb = 5
            settings.duckdb_cache_ttl_hours = 24
            settings.duckdb_max_query_rows = 5000
            settings.duckdb_query_timeout = 30

            service = DuckDBQueryService()
            result = service.execute_query(
                attachment_id=999,
                sql="SELECT * FROM data_db.sales",
            )
            assert result["success"] is False
            assert "No DuckDB cache" in result["error"]

    def test_get_schema_no_cache(self, tmp_path):
        """Schema returns error when no cached file exists."""
        with patch(
            "knowledge_runtime.services.duckdb_query.get_settings"
        ) as mock_settings:
            settings = mock_settings.return_value
            settings.duckdb_cache_dir = str(tmp_path)
            settings.duckdb_cache_max_size_gb = 5
            settings.duckdb_cache_ttl_hours = 24
            settings.duckdb_max_query_rows = 5000
            settings.duckdb_query_timeout = 30

            service = DuckDBQueryService()
            result = service.get_schema(attachment_id=999)
            assert "No DuckDB cache" in result["error"]


# Need to import patch for the test above
from unittest.mock import patch
