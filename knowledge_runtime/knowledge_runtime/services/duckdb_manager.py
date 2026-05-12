# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""DuckDB connection manager with local file caching.

Manages the lifecycle of .duckdb files on the local filesystem,
including LRU eviction, TTL expiry, and integrity verification.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from knowledge_runtime.config import get_settings

logger = logging.getLogger(__name__)


class DuckDBManager:
    """Manages local DuckDB file cache with LRU and TTL policies."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._cache_dir = Path(self._settings.duckdb_cache_dir)
        self._ensure_cache_dir()

    def _ensure_cache_dir(self) -> None:
        """Create cache directory if it does not exist."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _cache_key(attachment_id: int) -> str:
        """Generate a deterministic cache filename from attachment_id."""
        raw = f"attachment_{attachment_id}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_duckdb_path(self, attachment_id: int) -> Path:
        """Return the local path for a given attachment's .duckdb file."""
        return self._cache_dir / f"{self._cache_key(attachment_id)}.duckdb"

    def has_cached(self, attachment_id: int, source_hash: Optional[str] = None) -> bool:
        """Check if a cached .duckdb file exists and optionally verify integrity.

        Args:
            attachment_id: The attachment ID to check.
            source_hash: Optional SHA256 of the source file for integrity check.

        Returns:
            True if a valid cached file exists.
        """
        path = self.get_duckdb_path(attachment_id)
        if not path.exists():
            return False

        # TTL check
        ttl_hours = self._settings.duckdb_cache_ttl_hours
        mtime = path.stat().st_mtime
        if time.time() - mtime > ttl_hours * 3600:
            logger.info(
                "Cached .duckdb for attachment %d expired (TTL=%dh)", attachment_id, ttl_hours
            )
            self.remove_cached(attachment_id)
            return False

        # Integrity hash check (stored as sidecar .hash file)
        if source_hash:
            hash_path = path.with_suffix(".hash")
            if hash_path.exists():
                stored_hash = hash_path.read_text().strip()
                if stored_hash != source_hash:
                    logger.info(
                        "Cached .duckdb for attachment %d hash mismatch, removing",
                        attachment_id,
                    )
                    self.remove_cached(attachment_id)
                    return False

        # Touch for LRU
        path.touch()
        return True

    def save_duckdb_file(
        self,
        attachment_id: int,
        source_path: Path,
        source_hash: Optional[str] = None,
    ) -> Path:
        """Copy a generated .duckdb file into the local cache.

        Args:
            attachment_id: The attachment ID.
            source_path: Path to the generated .duckdb file.
            source_hash: Optional SHA256 of the source Excel/CSV file.

        Returns:
            Path to the cached .duckdb file.
        """
        dest_path = self.get_duckdb_path(attachment_id)

        # Evict if cache is too large
        self._evict_if_needed()

        shutil.copy2(source_path, dest_path)

        # Store source hash as sidecar for integrity checks
        if source_hash:
            hash_path = dest_path.with_suffix(".hash")
            hash_path.write_text(source_hash)

        logger.info(
            "Cached .duckdb for attachment %d at %s (%d bytes)",
            attachment_id,
            dest_path,
            dest_path.stat().st_size,
        )
        return dest_path

    def remove_cached(self, attachment_id: int) -> None:
        """Remove cached .duckdb and sidecar files for an attachment."""
        path = self.get_duckdb_path(attachment_id)
        if path.exists():
            path.unlink()
        hash_path = path.with_suffix(".hash")
        if hash_path.exists():
            hash_path.unlink()

    def _evict_if_needed(self) -> None:
        """Evict oldest files if cache exceeds max size."""
        max_bytes = self._settings.duckdb_cache_max_size_gb * 1024 * 1024 * 1024
        total = self._total_cache_size()
        if total <= max_bytes:
            return

        # Sort by mtime ascending (oldest first)
        files = sorted(self._cache_dir.glob("*.duckdb"), key=lambda p: p.stat().st_mtime)

        for f in files:
            if total <= max_bytes:
                break
            size = f.stat().st_size
            f.unlink()
            hash_path = f.with_suffix(".hash")
            if hash_path.exists():
                hash_path.unlink()
            total -= size
            logger.info("Evicted cached .duckdb: %s (%d bytes)", f.name, size)

    def _total_cache_size(self) -> int:
        """Total size of all .duckdb files in the cache directory."""
        return sum(f.stat().st_size for f in self._cache_dir.glob("*.duckdb"))


# Module-level singleton
_duckdb_manager: Optional[DuckDBManager] = None


def get_duckdb_manager() -> DuckDBManager:
    """Get the global DuckDB manager instance."""
    global _duckdb_manager
    if _duckdb_manager is None:
        _duckdb_manager = DuckDBManager()
    return _duckdb_manager
