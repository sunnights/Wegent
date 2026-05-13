# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Post-processor that executes DuckDB queries returned by Backend MCP tools.

Backend's ``wegent_data_query`` / ``wegent_data_schema`` MCP tools return a
``ContentRef`` + SQL + human-readable instruction telling the caller to
download the ``.duckdb`` file and run the query locally. The Executor
(ClaudeCode) already does this transparently. This post-processor gives
Chat Shell the same capability — by rewriting the tool's returned payload
with concrete query results before the LLM ever sees it.

If execution fails (e.g. sandbox runner unavailable, download error), we
leave the raw Backend response untouched so the LLM can at least describe
the problem to the user rather than fail silently.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from chat_shell.services.duckdb_sandbox_runner import get_shared_duckdb_runner
from chat_shell.tools.mcp.post_processors.base import (
    PostProcessorContext,
    default_registry,
)

logger = logging.getLogger(__name__)

# Backend MCP tool names we intercept. Kept in one place so the Backend can
# rename them without us hunting string literals.
TOOL_NAME_QUERY = "wegent_data_query"
TOOL_NAME_SCHEMA = "wegent_data_schema"


# ---------------------------------------------------------------------------
# Payload decoding helpers
# ---------------------------------------------------------------------------


def _decode_payload(result: Any) -> tuple[Optional[dict[str, Any]], Any, bool]:
    """Attempt to extract a JSON payload from an MCP tool result.

    MCP tools returned via langchain-mcp-adapters can surface as:

    - a plain ``str`` (JSON text)
    - a ``(content, artifact)`` tuple (``response_format == "content_and_artifact"``)
    - already-parsed dicts (older code paths / tests)

    Returns:
        ``(payload, artifact, is_tuple_shape)`` where ``payload`` is the
        decoded dict (or ``None`` if it isn't parseable), ``artifact`` is the
        optional artifact portion, and ``is_tuple_shape`` indicates that the
        original was a 2-tuple so the caller can re-pack in the same shape.
    """
    if isinstance(result, tuple) and len(result) == 2:
        content, artifact = result
        payload, _, _ = _decode_payload(content)
        return payload, artifact, True

    if isinstance(result, dict):
        return result, None, False

    if isinstance(result, str):
        stripped = result.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                decoded = json.loads(stripped)
                if isinstance(decoded, dict):
                    return decoded, None, False
            except json.JSONDecodeError:
                return None, None, False
        return None, None, False

    return None, None, False


def _repack(
    payload: dict[str, Any],
    *,
    artifact: Any,
    is_tuple_shape: bool,
    prefer_string: bool,
) -> Any:
    """Repack a mutated payload into the original MCP result shape."""
    if prefer_string:
        text = json.dumps(payload, ensure_ascii=False)
        if is_tuple_shape:
            return text, artifact
        return text

    if is_tuple_shape:
        return payload, artifact
    return payload


# ---------------------------------------------------------------------------
# Core post-processors
# ---------------------------------------------------------------------------


async def _process_query(
    *,
    result: Any,
    context: PostProcessorContext,
) -> Any:
    """Handle ``wegent_data_query`` tool results."""
    payload, artifact, is_tuple_shape = _decode_payload(result)
    if payload is None:
        return result  # unknown shape, leave untouched

    if not payload.get("success"):
        return result  # Backend reported failure, nothing to execute

    content_ref = payload.get("content_ref")
    sql = payload.get("sql")
    attachment_id = payload.get("attachment_id") or _extract_attachment_id_from_ref(
        content_ref
    )

    if not content_ref or not sql:
        return result  # Insufficient info to run locally

    task_id = context.task_id
    if task_id is None:
        logger.debug(
            "[duckdb_post_processor] Skipping %s — no task_id in context",
            context.tool_name,
        )
        return result

    try:
        runner = await get_shared_duckdb_runner()
        query_result = await runner.run_query(
            task_id=int(task_id),
            attachment_id=int(attachment_id) if attachment_id is not None else 0,
            content_ref=content_ref,
            sql=sql,
        )
    except Exception as exc:
        logger.exception("[duckdb_post_processor] Query execution failed: %s", exc)
        return result

    merged = {
        **payload,
        "success": query_result.get("success", False),
        "result": query_result,
    }
    if not query_result.get("success"):
        merged["error"] = query_result.get("error", "Query execution failed")

    # Drop the now-irrelevant instruction so the LLM doesn't hallucinate
    # "please download the file" steps.
    merged.pop("instruction", None)

    prefer_string = isinstance(result, str) or (
        is_tuple_shape and isinstance(result[0], str)
    )
    return _repack(
        merged,
        artifact=artifact,
        is_tuple_shape=is_tuple_shape,
        prefer_string=prefer_string,
    )


async def _process_schema(
    *,
    result: Any,
    context: PostProcessorContext,
) -> Any:
    """Handle ``wegent_data_schema`` tool results.

    The schema tool already embeds schema info in its response, so the
    primary job here is to surface the ``source_file_hash`` (if provided)
    and ensure the ContentRef is reachable from the Chat Shell cache — we
    don't need to *execute* anything against DuckDB.

    We still attempt to download the file so the cache is warm for the
    subsequent query call; failures are non-fatal.
    """
    payload, artifact, is_tuple_shape = _decode_payload(result)
    if payload is None or not payload.get("success"):
        return result

    content_ref = payload.get("content_ref")
    attachment_id = payload.get("attachment_id")

    if content_ref and attachment_id is not None and context.task_id is not None:
        try:
            runner = await get_shared_duckdb_runner()
            # Fire-and-forget warm up: drop errors quietly to keep the
            # schema response deterministic for the LLM.
            await runner.run_schema(
                task_id=int(context.task_id),
                attachment_id=int(attachment_id),
                content_ref=content_ref,
            )
        except Exception as exc:
            logger.debug(
                "[duckdb_post_processor] Schema warm-up failed (non-fatal): %s",
                exc,
            )

    return result


def _extract_attachment_id_from_ref(content_ref: Any) -> Optional[int]:
    """Best-effort attempt to derive the attachment ID from a ContentRef URL.

    Some Backend responses omit a top-level ``attachment_id`` in the query
    payload (see ``wegent_data_query``) and only expose it implicitly via the
    URL suffix (e.g. ``/api/internal/rag/content/99``). We parse that suffix
    here so the runner can still scope its cache correctly.
    """
    if not isinstance(content_ref, dict):
        return None
    url = content_ref.get("url") or ""
    if not url:
        return None
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    try:
        return int(tail)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_duckdb_post_processors(registry=default_registry) -> None:
    """Register the DuckDB post-processors on the given registry.

    Called once at Chat Shell process startup. Safe to call more than once;
    registering the same tool twice logs a warning but is otherwise harmless.
    """
    registry.register(TOOL_NAME_QUERY, _process_query)
    registry.register(TOOL_NAME_SCHEMA, _process_schema)


__all__ = [
    "register_duckdb_post_processors",
    "TOOL_NAME_QUERY",
    "TOOL_NAME_SCHEMA",
]
