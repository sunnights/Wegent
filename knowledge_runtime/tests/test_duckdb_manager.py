# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for DuckDB manager service."""

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from knowledge_runtime.config import reset_settings
from knowledge_runtime.services.duckdb_manager import DuckDBManager


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset settings before each test."""
    reset_settings()
    yield
    reset_settings()


class TestDuckDBManager:
    """Tests for DuckDBManager local cache management."""

    def test_cache_key_deterministic(self):
        """Cache key is deterministic for the same attachment_id."""
        key1 = DuckDBManager._cache_key(42)
        key2 = DuckDBManager._cache_key(42)
        assert key1 == key2

    def test_cache_key_different_for_different_ids(self):
        """Cache key differs for different attachment_ids."""
        key1 = DuckDBManager._cache_key(1)
        key2 = DuckDBManager._cache_key(2)
        assert key1 != key2

    def test_get_duckdb_path(self, tmp_path):
        """get_duckdb_path returns path within cache directory."""
        with patch(
            "knowledge_runtime.services.duckdb_manager.get_settings"
        ) as mock_settings:
            settings = mock_settings.return_value
            settings.duckdb_cache_dir = str(tmp_path)
            settings.duckdb_cache_max_size_gb = 5
            settings.duckdb_cache_ttl_hours = 24

            manager = DuckDBManager()
            path = manager.get_duckdb_path(123)
            assert str(path).startswith(str(tmp_path))
            assert path.suffix == ".duckdb"

    def test_has_cached_no_file(self, tmp_path):
        """has_cached returns False when no file exists."""
        with patch(
            "knowledge_runtime.services.duckdb_manager.get_settings"
        ) as mock_settings:
            settings = mock_settings.return_value
            settings.duckdb_cache_dir = str(tmp_path)
            settings.duckdb_cache_max_size_gb = 5
            settings.duckdb_cache_ttl_hours = 24

            manager = DuckDBManager()
            assert manager.has_cached(999) is False

    def test_save_and_has_cached(self, tmp_path):
        """save_duckdb_file creates cached file and has_cached finds it."""
        with patch(
            "knowledge_runtime.services.duckdb_manager.get_settings"
        ) as mock_settings:
            settings = mock_settings.return_value
            settings.duckdb_cache_dir = str(tmp_path)
            settings.duckdb_cache_max_size_gb = 5
            settings.duckdb_cache_ttl_hours = 24

            manager = DuckDBManager()

            # Create a dummy .duckdb file
            source = tmp_path / "source.duckdb"
            source.write_bytes(b"test duckdb content")

            cached_path = manager.save_duckdb_file(123, source, source_hash="abc123")
            assert cached_path.exists()
            assert manager.has_cached(123) is True

    def test_has_cached_with_hash_mismatch(self, tmp_path):
        """has_cached returns False when source hash doesn't match."""
        with patch(
            "knowledge_runtime.services.duckdb_manager.get_settings"
        ) as mock_settings:
            settings = mock_settings.return_value
            settings.duckdb_cache_dir = str(tmp_path)
            settings.duckdb_cache_max_size_gb = 5
            settings.duckdb_cache_ttl_hours = 24

            manager = DuckDBManager()

            source = tmp_path / "source.duckdb"
            source.write_bytes(b"test duckdb content")

            manager.save_duckdb_file(123, source, source_hash="hash_v1")

            # Should return False when hash doesn't match
            assert manager.has_cached(123, source_hash="hash_v2") is False

    def test_has_cached_with_hash_match(self, tmp_path):
        """has_cached returns True when source hash matches."""
        with patch(
            "knowledge_runtime.services.duckdb_manager.get_settings"
        ) as mock_settings:
            settings = mock_settings.return_value
            settings.duckdb_cache_dir = str(tmp_path)
            settings.duckdb_cache_max_size_gb = 5
            settings.duckdb_cache_ttl_hours = 24

            manager = DuckDBManager()

            source = tmp_path / "source.duckdb"
            source.write_bytes(b"test duckdb content")

            manager.save_duckdb_file(123, source, source_hash="hash_v1")

            # Should return True when hash matches
            assert manager.has_cached(123, source_hash="hash_v1") is True

    def test_remove_cached(self, tmp_path):
        """remove_cached deletes cached file."""
        with patch(
            "knowledge_runtime.services.duckdb_manager.get_settings"
        ) as mock_settings:
            settings = mock_settings.return_value
            settings.duckdb_cache_dir = str(tmp_path)
            settings.duckdb_cache_max_size_gb = 5
            settings.duckdb_cache_ttl_hours = 24

            manager = DuckDBManager()

            source = tmp_path / "source.duckdb"
            source.write_bytes(b"test")

            manager.save_duckdb_file(456, source)
            assert manager.has_cached(456) is True

            manager.remove_cached(456)
            assert manager.has_cached(456) is False

    def test_ttl_expiry(self, tmp_path):
        """has_cached returns False when cache file is expired."""
        with patch(
            "knowledge_runtime.services.duckdb_manager.get_settings"
        ) as mock_settings:
            settings = mock_settings.return_value
            settings.duckdb_cache_dir = str(tmp_path)
            settings.duckdb_cache_max_size_gb = 5
            settings.duckdb_cache_ttl_hours = 0  # Immediate expiry

            manager = DuckDBManager()

            source = tmp_path / "source.duckdb"
            source.write_bytes(b"test")

            manager.save_duckdb_file(789, source)

            # Should be expired immediately
            assert manager.has_cached(789) is False
