# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the DuckDB MCP post-processor."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from chat_shell.tools.mcp.post_processors.base import (
    MCPPostProcessorRegistry,
    PostProcessorContext,
)
from chat_shell.tools.mcp.post_processors.duckdb_post_processor import (
    TOOL_NAME_QUERY,
    TOOL_NAME_SCHEMA,
    _decode_payload,
    _extract_attachment_id_from_ref,
    _process_query,
    register_duckdb_post_processors,
)

# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------


class TestDecodePayload:
    def test_plain_dict(self) -> None:
        payload, artifact, is_tuple = _decode_payload({"success": True})
        assert payload == {"success": True}
        assert artifact is None
        assert is_tuple is False

    def test_json_string(self) -> None:
        payload, artifact, is_tuple = _decode_payload('{"success": true}')
        assert payload == {"success": True}
        assert is_tuple is False

    def test_content_and_artifact_tuple(self) -> None:
        payload, artifact, is_tuple = _decode_payload(
            (
                '{"success": true, "value": 1}',
                {"meta": "artifact"},
            )
        )
        assert payload == {"success": True, "value": 1}
        assert artifact == {"meta": "artifact"}
        assert is_tuple is True

    def test_non_json_string(self) -> None:
        payload, _, _ = _decode_payload("plain text")
        assert payload is None

    def test_unknown_type(self) -> None:
        payload, _, _ = _decode_payload(12345)
        assert payload is None


class TestExtractAttachmentId:
    def test_url_ends_with_numeric_id(self) -> None:
        assert (
            _extract_attachment_id_from_ref(
                {"url": "http://backend/api/internal/rag/content/99"}
            )
            == 99
        )

    def test_non_numeric_tail(self) -> None:
        assert (
            _extract_attachment_id_from_ref({"url": "http://backend/file.duckdb"})
            is None
        )

    def test_missing_content_ref(self) -> None:
        assert _extract_attachment_id_from_ref(None) is None
        assert _extract_attachment_id_from_ref({}) is None


# ---------------------------------------------------------------------------
# _process_query
# ---------------------------------------------------------------------------


@pytest.fixture
def query_success_payload():
    return {
        "success": True,
        "content_ref": {
            "kind": "backend_attachment_stream",
            "url": "http://backend/api/internal/rag/content/99",
            "auth_token": "tok",
        },
        "tables": ["sales"],
        "sql": "SELECT * FROM data_db.sales",
        "instruction": "Download and run locally.",
    }


class TestProcessQuery:
    @pytest.mark.asyncio
    async def test_replaces_instruction_with_result(
        self, query_success_payload
    ) -> None:
        """Successful query result is merged into payload, instruction dropped."""
        runner = AsyncMock()
        runner.run_query = AsyncMock(
            return_value={
                "success": True,
                "columns": ["id"],
                "rows": [[1]],
                "row_count": 1,
                "truncated": False,
            }
        )

        with patch(
            "chat_shell.tools.mcp.post_processors.duckdb_post_processor"
            ".get_shared_duckdb_runner",
            AsyncMock(return_value=runner),
        ):
            result = await _process_query(
                result=json.dumps(query_success_payload),
                context=PostProcessorContext(
                    tool_name=TOOL_NAME_QUERY, task_id=42, user_id=7
                ),
            )

        assert isinstance(result, str)
        merged = json.loads(result)
        assert merged["success"] is True
        assert merged["result"]["rows"] == [[1]]
        assert "instruction" not in merged
        runner.run_query.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_query_execution_failure_sets_error(
        self, query_success_payload
    ) -> None:
        runner = AsyncMock()
        runner.run_query = AsyncMock(
            return_value={"success": False, "error": "syntax error"}
        )

        with patch(
            "chat_shell.tools.mcp.post_processors.duckdb_post_processor"
            ".get_shared_duckdb_runner",
            AsyncMock(return_value=runner),
        ):
            result = await _process_query(
                result=query_success_payload,
                context=PostProcessorContext(tool_name=TOOL_NAME_QUERY, task_id=42),
            )

        assert isinstance(result, dict)
        assert result["success"] is False
        assert result["error"] == "syntax error"

    @pytest.mark.asyncio
    async def test_leaves_unchanged_when_success_false(self) -> None:
        """Backend errors should pass through untouched."""
        payload = {"success": False, "error": "nope"}
        result = await _process_query(
            result=payload,
            context=PostProcessorContext(tool_name=TOOL_NAME_QUERY, task_id=1),
        )
        assert result is payload

    @pytest.mark.asyncio
    async def test_skips_when_no_task_id(self, query_success_payload) -> None:
        """Without a task_id we cannot scope the cache, so we must no-op."""
        result = await _process_query(
            result=query_success_payload,
            context=PostProcessorContext(tool_name=TOOL_NAME_QUERY),
        )
        assert result is query_success_payload

    @pytest.mark.asyncio
    async def test_runner_exception_falls_back_to_original(
        self, query_success_payload
    ) -> None:
        """If the runner blows up we must return the original payload."""
        with patch(
            "chat_shell.tools.mcp.post_processors.duckdb_post_processor"
            ".get_shared_duckdb_runner",
            AsyncMock(side_effect=RuntimeError("sandbox exploded")),
        ):
            result = await _process_query(
                result=query_success_payload,
                context=PostProcessorContext(tool_name=TOOL_NAME_QUERY, task_id=1),
            )
        assert result is query_success_payload


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registers_both_tool_names(self) -> None:
        registry = MCPPostProcessorRegistry()
        register_duckdb_post_processors(registry)
        assert registry.get(TOOL_NAME_QUERY) is not None
        assert registry.get(TOOL_NAME_SCHEMA) is not None

    def test_registration_is_idempotent(self) -> None:
        registry = MCPPostProcessorRegistry()
        register_duckdb_post_processors(registry)
        register_duckdb_post_processors(registry)
        assert len(registry.registered_tools()) == 2
