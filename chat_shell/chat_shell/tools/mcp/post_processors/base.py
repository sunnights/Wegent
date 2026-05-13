# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Core types + registry for MCP post-processors."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol

logger = logging.getLogger(__name__)


@dataclass
class PostProcessorContext:
    """Contextual info passed to every post-processor invocation.

    The ``task_data`` and ``task_id`` fields are populated from
    :class:`shared.models.execution.ExecutionRequest` when the MCP client is
    configured. Post-processors should treat these as optional since unit
    tests may invoke the registry directly without a task context.
    """

    tool_name: str
    server_name: Optional[str] = None
    task_id: Optional[int] = None
    user_id: Optional[int] = None
    extras: dict[str, Any] = field(default_factory=dict)


class MCPPostProcessor(Protocol):
    """Protocol implemented by a post-processor callable.

    A post-processor receives the tool's raw result and may return a new
    result of the same shape, or ``None`` to leave the original result
    untouched.
    """

    async def __call__(
        self,
        *,
        result: Any,
        context: PostProcessorContext,
    ) -> Any: ...


# Type alias used for the async callable signature
PostProcessorFn = Callable[..., Awaitable[Any]]


class MCPPostProcessorRegistry:
    """Registry of tool-name -> post-processor mappings.

    A given tool can only have one post-processor registered; calling
    :meth:`register` for the same tool twice overwrites the previous entry
    (but a warning is logged).
    """

    def __init__(self) -> None:
        self._processors: dict[str, PostProcessorFn] = {}

    def register(self, tool_name: str, processor: PostProcessorFn) -> None:
        if tool_name in self._processors:
            logger.warning(
                "[MCP][post_processor] Overwriting existing post-processor for tool '%s'",
                tool_name,
            )
        self._processors[tool_name] = processor
        logger.debug(
            "[MCP][post_processor] Registered post-processor for tool '%s'", tool_name
        )

    def unregister(self, tool_name: str) -> None:
        self._processors.pop(tool_name, None)

    def get(self, tool_name: str) -> Optional[PostProcessorFn]:
        return self._processors.get(tool_name)

    def registered_tools(self) -> list[str]:
        return list(self._processors.keys())


# Process-wide default registry. Feature modules register their processors
# at import time; the MCP client looks them up here.
default_registry = MCPPostProcessorRegistry()
