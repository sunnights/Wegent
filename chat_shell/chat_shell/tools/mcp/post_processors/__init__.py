# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Post-processing hooks for MCP tool results.

A post-processor is an ``async`` callable that takes the raw result returned
by an MCP tool (either a ``str`` or a ``(content, artifact)`` tuple, depending
on the tool's ``response_format``) and transforms it before handing it back to
the LLM.

The registry lives on :class:`chat_shell.tools.mcp.client.MCPClient`. Tools
are wrapped with post-processors in
:func:`chat_shell.tools.mcp.client.wrap_tool_with_protection` (via
``wrap_tool_with_post_processor``); tools without a matching post-processor
are returned unchanged.

This lets features such as DuckDB data-analysis transparently rewrite a
ContentRef + SQL instruction into concrete query results without touching
the Backend MCP server, the AI prompt, or any skill definition.
"""

from __future__ import annotations

from .base import (
    MCPPostProcessor,
    MCPPostProcessorRegistry,
    PostProcessorContext,
    default_registry,
)

__all__ = [
    "MCPPostProcessor",
    "MCPPostProcessorRegistry",
    "PostProcessorContext",
    "default_registry",
]
