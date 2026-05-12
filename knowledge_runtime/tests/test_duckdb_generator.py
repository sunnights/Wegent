# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for DuckDB generator service."""

import pytest

from knowledge_runtime.config import reset_settings
from knowledge_runtime.services.duckdb_generator import (
    DuckDBGenerator,
    _sanitize_table_name,
)


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset settings before each test."""
    reset_settings()
    yield
    reset_settings()


class TestSanitizeTableName:
    """Tests for table name sanitization."""

    def test_simple_name(self):
        assert _sanitize_table_name("sales") == "sales"

    def test_name_with_spaces(self):
        assert _sanitize_table_name("Sales Data") == "sales_data"

    def test_name_with_special_chars(self):
        assert _sanitize_table_name("Sales-2024.Q1") == "sales_2024_q1"

    def test_name_starting_with_digit(self):
        assert _sanitize_table_name("2024_sales") == "t_2024_sales"

    def test_name_with_chinese_chars(self):
        # Chinese characters are replaced with underscores
        result = _sanitize_table_name("销售数据")
        assert result.startswith("t_")  # Starts with non-alpha, prefixed

    def test_empty_name(self):
        result = _sanitize_table_name("")
        assert result == ""


class TestDuckDBGenerator:
    """Tests for DuckDBGenerator."""

    @pytest.mark.asyncio
    async def test_generate_unsupported_extension(self, tmp_path):
        """Generate returns error for unsupported file extensions."""
        with patch(
            "knowledge_runtime.services.duckdb_generator.get_settings"
        ) as mock_settings:
            settings = mock_settings.return_value
            settings.duckdb_max_file_size_mb = 500
            settings.duckdb_min_free_memory_mb = 1024
            settings.duckdb_cache_dir = str(tmp_path)
            settings.duckdb_cache_max_size_gb = 5
            settings.duckdb_cache_ttl_hours = 24
            settings.duckdb_summary_sample_rows = 50
            settings.duckdb_memory_limit = "4GB"

            generator = DuckDBGenerator()
            result = await generator.generate(
                attachment_id=1,
                binary_data=b"test",
                source_file="test.pdf",
                file_extension=".pdf",
            )
            assert result["success"] is False
            assert "Unsupported" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_file_too_large(self, tmp_path):
        """Generate returns error when file exceeds size limit."""
        with patch(
            "knowledge_runtime.services.duckdb_generator.get_settings"
        ) as mock_settings:
            settings = mock_settings.return_value
            settings.duckdb_max_file_size_mb = 0  # 0 MB limit
            settings.duckdb_min_free_memory_mb = 1024
            settings.duckdb_cache_dir = str(tmp_path)
            settings.duckdb_cache_max_size_gb = 5
            settings.duckdb_cache_ttl_hours = 24
            settings.duckdb_summary_sample_rows = 50
            settings.duckdb_memory_limit = "4GB"

            generator = DuckDBGenerator()
            result = await generator.generate(
                attachment_id=1,
                binary_data=b"x" * 1000,
                source_file="test.xlsx",
                file_extension=".xlsx",
            )
            assert result["success"] is False
            assert "too large" in result["error"].lower()


# Need to import patch for the test above
from unittest.mock import patch
