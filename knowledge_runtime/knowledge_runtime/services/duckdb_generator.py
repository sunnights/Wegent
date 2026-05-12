# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""DuckDB generator service for importing Excel/CSV files.

Handles the write-connection lifecycle: import data via DuckDB's
read_xlsx/read_csv_auto, execute SUMMARIZE, extract samples,
CHECKPOINT, and close the write connection.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from knowledge_runtime.config import get_settings
from knowledge_runtime.services.duckdb_manager import get_duckdb_manager

logger = logging.getLogger(__name__)

# Supported file extensions for DuckDB import
SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".tsv"}


def _sanitize_table_name(name: str) -> str:
    """Convert a file/sheet name to a valid DuckDB table name.

    Replaces non-alphanumeric characters with underscores and
    ensures the name starts with a letter.
    """
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if name and not name[0].isalpha():
        name = f"t_{name}"
    return name.lower()


def _check_available_memory() -> bool:
    """Check if system has enough free memory for DuckDB generation."""
    try:
        import psutil

        available_mb = psutil.virtual_memory().available // (1024 * 1024)
        settings = get_settings()
        if available_mb < settings.duckdb_min_free_memory_mb:
            logger.warning(
                "Insufficient memory for DuckDB generation: %dMB available, %dMB required",
                available_mb,
                settings.duckdb_min_free_memory_mb,
            )
            return False
        return True
    except ImportError:
        # psutil not available, proceed with generation
        logger.debug("psutil not available, skipping memory check")
        return True


class DuckDBGenerator:
    """Generates .duckdb files from Excel/CSV attachments."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._manager = get_duckdb_manager()

    async def generate(
        self,
        attachment_id: int,
        binary_data: bytes,
        source_file: str,
        file_extension: str,
    ) -> dict[str, Any]:
        """Generate a .duckdb file from an Excel/CSV attachment.

        Args:
            attachment_id: The attachment ID.
            binary_data: Raw binary data of the source file.
            source_file: Original filename.
            file_extension: File extension (e.g., ".xlsx", ".csv").

        Returns:
            Dict with generation results: success, summary, tables, etc.
        """
        start_time = time.time()
        ext = file_extension.lower()

        if ext not in SUPPORTED_EXTENSIONS:
            return {
                "success": False,
                "attachment_id": attachment_id,
                "duckdb_attachment_id": None,
                "summary": None,
                "tables": [],
                "generation_time_ms": 0,
                "error": f"Unsupported file extension: {ext}",
            }

        # Check file size
        max_size_bytes = self._settings.duckdb_max_file_size_mb * 1024 * 1024
        if len(binary_data) > max_size_bytes:
            return {
                "success": False,
                "attachment_id": attachment_id,
                "duckdb_attachment_id": None,
                "summary": None,
                "tables": [],
                "generation_time_ms": 0,
                "error": (
                    f"File too large: {len(binary_data)} bytes exceeds "
                    f"{self._settings.duckdb_max_file_size_mb}MB limit"
                ),
            }

        # Check available memory
        if not _check_available_memory():
            return {
                "success": False,
                "attachment_id": attachment_id,
                "duckdb_attachment_id": None,
                "summary": None,
                "tables": [],
                "generation_time_ms": 0,
                "error": "Insufficient system memory for DuckDB generation",
            }

        # Compute source file hash for integrity
        source_hash = hashlib.sha256(binary_data).hexdigest()

        # Write source file to temp location for DuckDB import
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_dir_path = Path(tmp_dir)
            source_path = tmp_dir_path / f"source{ext}"
            source_path.write_bytes(binary_data)

            duckdb_path = tmp_dir_path / "data.duckdb"

            try:
                import duckdb
            except ImportError:
                return {
                    "success": False,
                    "attachment_id": attachment_id,
                    "duckdb_attachment_id": None,
                    "summary": None,
                    "tables": [],
                    "generation_time_ms": 0,
                    "error": "DuckDB is not installed",
                }

            try:
                tables_info = self._import_and_generate(
                    duckdb, source_path, duckdb_path, ext, source_file
                )
            except Exception as e:
                logger.error(
                    "DuckDB generation failed for attachment %d: %s", attachment_id, e
                )
                return {
                    "success": False,
                    "attachment_id": attachment_id,
                    "duckdb_attachment_id": None,
                    "summary": None,
                    "tables": [],
                    "generation_time_ms": (time.time() - start_time) * 1000,
                    "error": str(e),
                }

            # Move generated .duckdb to cache
            if duckdb_path.exists():
                cached_path = self._manager.save_duckdb_file(
                    attachment_id, duckdb_path, source_hash
                )
                logger.info(
                    "Generated .duckdb for attachment %d: %s", attachment_id, cached_path
                )

        # Build summary from tables_info
        summary = self._build_summary(tables_info)

        elapsed_ms = (time.time() - start_time) * 1000
        return {
            "success": True,
            "attachment_id": attachment_id,
            "duckdb_attachment_id": None,  # Set by caller after uploading
            "summary": summary,
            "tables": [
                {"name": t["name"], "rows": t["row_count"]} for t in tables_info
            ],
            "generation_time_ms": elapsed_ms,
            "error": None,
        }

    def _import_and_generate(
        self,
        duckdb_module: Any,
        source_path: Path,
        duckdb_path: Path,
        ext: str,
        source_file: str,
    ) -> list[dict[str, Any]]:
        """Import data into DuckDB and generate summary information.

        Args:
            duckdb_module: The imported duckdb module.
            source_path: Path to the source Excel/CSV file.
            duckdb_path: Path where the .duckdb file will be created.
            ext: File extension.
            source_file: Original filename.

        Returns:
            List of table info dicts with name, row_count, columns, sample_data.
        """
        import duckdb  # noqa: F811 - re-import for clarity

        settings = self._settings
        conn = duckdb.connect(str(duckdb_path))
        tables_info: list[dict[str, Any]] = []

        try:
            # Configure connection
            conn.execute(f"SET memory_limit = '{settings.duckdb_memory_limit}'")
            conn.execute("SET temp_directory = '/tmp/duckdb_spill'")
            conn.execute("SET preserve_insertion_order = false")

            if ext == ".xlsx":
                tables_info = self._import_xlsx(conn, duckdb, source_path, source_file)
            elif ext in (".csv", ".tsv"):
                tables_info = self._import_csv(conn, duckdb, source_path, source_file)
            elif ext == ".xls":
                # .xls is legacy format; try openpyxl-based fallback
                tables_info = self._import_xls_fallback(conn, duckdb, source_path, source_file)

            # Generate summary info for each table
            for table_info in tables_info:
                table_name = table_info["name"]
                try:
                    # Get SUMMARIZE info
                    summarize_result = conn.execute(
                        f"SUMMARIZE {table_name}"
                    ).fetchall()
                    table_info["summarize"] = self._format_summarize(summarize_result)

                    # Get sample rows
                    sample_rows = settings.duckdb_summary_sample_rows
                    sample_result = conn.execute(
                        f"SELECT * FROM {table_name} LIMIT {sample_rows}"
                    ).fetchall()
                    columns = [desc[0] for desc in conn.execute(f"SELECT * FROM {table_name} LIMIT 0").description]
                    table_info["sample_data"] = {
                        "columns": columns,
                        "rows": [list(row) for row in sample_result],
                    }

                    # Get row count
                    count_result = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
                    table_info["row_count"] = count_result[0] if count_result else 0

                except Exception as e:
                    logger.warning(
                        "Failed to generate summary for table %s: %s", table_name, e
                    )
                    table_info["summarize"] = []
                    table_info["sample_data"] = {"columns": [], "rows": []}
                    table_info["row_count"] = 0

            # Ensure WAL is merged
            conn.execute("CHECKPOINT")
        finally:
            conn.close()

        return tables_info

    def _import_xlsx(
        self,
        conn: Any,
        duckdb_module: Any,
        source_path: Path,
        source_file: str,
    ) -> list[dict[str, Any]]:
        """Import an .xlsx file using DuckDB's excel extension."""
        # Install and load excel extension
        conn.execute("INSTALL excel")
        conn.execute("LOAD excel")

        # Read sheet names
        try:
            sheet_info = conn.execute(
                "SELECT sheet_name FROM excel_sheet_info(?)", [str(source_path)]
            ).fetchall()
            sheet_names = [row[0] for row in sheet_info]
        except Exception:
            # Fallback: try reading as single sheet
            sheet_names = []

        tables_info = []
        base_name = _sanitize_table_name(Path(source_file).stem)

        if not sheet_names:
            # Single table from file
            table_name = base_name
            conn.execute(
                f"CREATE TABLE {table_name} AS SELECT * FROM read_xlsx(?, header=true)",
                [str(source_path)],
            )
            tables_info.append({"name": table_name})
        else:
            # Multiple sheets
            used_names: dict[str, int] = {}
            for sheet_name in sheet_names:
                table_name = f"sheet_{_sanitize_table_name(sheet_name)}"
                # Handle name conflicts
                if table_name in used_names:
                    used_names[table_name] += 1
                    table_name = f"{table_name}_{used_names[table_name]}"
                else:
                    used_names[table_name] = 0

                try:
                    conn.execute(
                        f"CREATE TABLE {table_name} AS SELECT * FROM read_xlsx(?, sheet=?, header=true)",
                        [str(source_path), sheet_name],
                    )
                    # Skip empty sheets (no data)
                    count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
                    if count and count[0] > 0:
                        tables_info.append({"name": table_name})
                    else:
                        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
                except Exception as e:
                    logger.warning(
                        "Failed to import sheet '%s' from %s: %s", sheet_name, source_file, e
                    )

        return tables_info

    def _import_csv(
        self,
        conn: Any,
        duckdb_module: Any,
        source_path: Path,
        source_file: str,
    ) -> list[dict[str, Any]]:
        """Import a CSV/TSV file using DuckDB's read_csv_auto."""
        base_name = _sanitize_table_name(Path(source_file).stem)
        conn.execute(
            f"CREATE TABLE {base_name} AS SELECT * FROM read_csv_auto(?)",
            [str(source_path)],
        )
        return [{"name": base_name}]

    def _import_xls_fallback(
        self,
        conn: Any,
        duckdb_module: Any,
        source_path: Path,
        source_file: str,
    ) -> list[dict[str, Any]]:
        """Import .xls file by first converting with openpyxl via pandas."""
        try:
            import pandas as pd
            from openpyxl import load_workbook

            # .xls files need to be converted first; attempt with pandas
            # pandas can read .xls via xlrd if available
            try:
                df = pd.read_excel(source_path, engine="xlrd")
            except Exception:
                # Try openpyxl for .xlsx files mislabeled as .xls
                df = pd.read_excel(source_path, engine="openpyxl")

            base_name = _sanitize_table_name(Path(source_file).stem)
            conn.execute(
                f"CREATE TABLE {base_name} AS SELECT * FROM df"
            )
            return [{"name": base_name}]
        except Exception as e:
            raise ValueError(
                f"Failed to import .xls file '{source_file}': {e}. "
                "Consider converting to .xlsx format."
            ) from e

    def _format_summarize(self, summarize_result: list[tuple]) -> list[dict[str, Any]]:
        """Format SUMMARIZE result into a list of column info dicts."""
        columns = []
        # SUMMARIZE columns: column_name, column_type, min, max, unique, avg, std, q25, q50, q75, count, null_percentage
        for row in summarize_result:
            col_info = {
                "column_name": row[0],
                "column_type": row[1],
                "min": str(row[2]) if row[2] is not None else None,
                "max": str(row[3]) if row[3] is not None else None,
                "unique": row[4] if row[4] is not None else None,
                "avg": round(row[5], 2) if row[5] is not None else None,
                "std": round(row[6], 2) if row[6] is not None else None,
                "null_percentage": round(row[11], 2) if len(row) > 11 and row[11] is not None else None,
            }
            columns.append(col_info)
        return columns

    def _build_summary(self, tables_info: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the summary dict from tables_info for storage."""
        tables_summary = []
        for table in tables_info:
            table_summary = {
                "name": table["name"],
                "row_count": table.get("row_count", 0),
                "columns": table.get("summarize", []),
            }
            tables_summary.append(table_summary)

        return {"tables": tables_summary}
