# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for DuckDB data analysis service in backend."""

import pytest

from app.services.data_analysis.duckdb_service import (
    DUCKDB_SUPPORTED_EXTENSIONS,
    DuckDBDataService,
)


class TestDuckDBDataService:
    """Tests for DuckDBDataService."""

    def test_is_supported_extension_xlsx(self):
        service = DuckDBDataService()
        assert service.is_supported_extension(".xlsx") is True

    def test_is_supported_extension_csv(self):
        service = DuckDBDataService()
        assert service.is_supported_extension(".csv") is True

    def test_is_supported_extension_xls(self):
        service = DuckDBDataService()
        assert service.is_supported_extension(".xls") is True

    def test_is_supported_extension_tsv(self):
        service = DuckDBDataService()
        assert service.is_supported_extension(".tsv") is True

    def test_is_not_supported_extension_pdf(self):
        service = DuckDBDataService()
        assert service.is_supported_extension(".pdf") is False

    def test_is_not_supported_extension_docx(self):
        service = DuckDBDataService()
        assert service.is_supported_extension(".docx") is False

    def test_supported_extensions_constant(self):
        assert ".xlsx" in DUCKDB_SUPPORTED_EXTENSIONS
        assert ".csv" in DUCKDB_SUPPORTED_EXTENSIONS
        assert ".xls" in DUCKDB_SUPPORTED_EXTENSIONS
        assert ".tsv" in DUCKDB_SUPPORTED_EXTENSIONS
        assert ".pdf" not in DUCKDB_SUPPORTED_EXTENSIONS

    def test_build_extracted_text_from_summary(self):
        """Test summary to extracted_text conversion."""
        service = DuckDBDataService()
        summary = {
            "tables": [
                {
                    "name": "sales_2024",
                    "row_count": 1000,
                    "columns": [
                        {
                            "column_name": "date",
                            "column_type": "DATE",
                            "min": "2024-01-01",
                            "max": "2024-12-31",
                            "unique": 366,
                            "avg": None,
                            "null_percentage": 0.0,
                        },
                        {
                            "column_name": "amount",
                            "column_type": "DOUBLE",
                            "min": "0.01",
                            "max": "9999.99",
                            "unique": None,
                            "avg": 1523.45,
                            "null_percentage": 2.0,
                        },
                    ],
                }
            ]
        }
        text = service.build_extracted_text_from_summary(summary, "sales_2024.xlsx")

        assert "Data Summary: sales_2024.xlsx" in text
        assert "Table: sales_2024" in text
        assert "1,000 rows" in text
        assert "date" in text
        assert "amount" in text
        assert "wegent_data_schema" in text
        assert "wegent_data_query" in text

    def test_build_extracted_text_empty_summary(self):
        """Test summary with no tables."""
        service = DuckDBDataService()
        text = service.build_extracted_text_from_summary({"tables": []}, "empty.xlsx")
        assert "Data Summary: empty.xlsx" in text
        assert "wegent_data_schema" in text
