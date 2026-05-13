---
sidebar_position: 10
---

# Chat Shell DuckDB Data Analysis Integration

## Background

The Wegent `wegent-data-analysis` Skill originally only supported **Claude Code Shell**: the AI fetches a ContentRef for a knowledge-base pre-generated `.duckdb` file via the Backend MCP tools `wegent_data_query` / `wegent_data_schema`, and the Executor container runs the queries locally with `DuckDBQueryExecutor`.

Chat Shell, the lightweight conversation engine, was not wired into this capability before this change. In conversational scenarios, asking questions about Excel/CSV data could only produce a ContentRef download link — an inconsistent user experience.

This document describes how Chat Shell transparently replaces the `wegent_data_query` ContentRef + SQL result with a real query result before it reaches the LLM, **without modifying the Backend, the Skill, or AI prompts**.

## Architecture

```text
 ┌───────────────────────────── Chat Shell ───────────────────────────┐
 │                                                                      │
 │  LangGraph Agent                                                     │
 │       │ tool call: wegent_data_query(attachment_id, sql)             │
 │       ▼                                                              │
 │  MCPClient → MCP Tool (via langchain-mcp-adapters)                   │
 │       │                                                              │
 │       ▼ raw result = {content_ref, sql, instruction, ...}            │
 │  ┌─────────────────────────────────────────────────────────────┐    │
 │  │  MCP Post-Processor Registry                                 │    │
 │  │    - wegent_data_query  → duckdb_post_processor              │    │
 │  │    - wegent_data_schema → duckdb_post_processor (warm-up)    │    │
 │  └─────────────────────────────────────────────────────────────┘    │
 │       │                                                              │
 │       ▼                                                              │
 │  ChatShellDuckDBRunner                                               │
 │    - Cache isolated by task_id                                       │
 │    - Reuses shared.services.duckdb_query.DuckDBQueryExecutor         │
 │    - :memory: + ATTACH READ_ONLY + enable_external_access=false      │
 │                                                                      │
 └──────────────────────────────────────────────────────────────────────┘
          ▲                                                ▲
          │                                                │
          │ Shared module                                  │ Downloads .duckdb (ContentRef)
          │                                                │
 ┌────────┴─────────────────┐              ┌───────────────┴──────────────┐
 │  Executor (ClaudeCode)   │              │  Backend                      │
 │  also uses               │              │  - /internal/rag/content/{id} │
 │  shared.services.duckdb_ │              │  - duckdb_cache table         │
 │  query                   │              └───────────────────────────────┘
 └──────────────────────────┘
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Execution location | In-process inside Chat Shell | `SandboxClient.execute()` only accepts prompts — no file upload or code execution primitives. DuckDB's security is enforced at the connection layer, so container isolation is not required. |
| Security controls | `ATTACH ... (READ_ONLY)` + `SET enable_external_access = false` | Equivalent to the Executor — disables writes and external access. |
| Triggering mechanism | MCP tool-result post-processor | Fully transparent to AI / Prompt / Skill / Backend. |
| Shared code | `shared/services/duckdb_query.py` | Executor and Chat Shell use the same implementation, ensuring consistent results. |
| Caching strategy | Per-`task_id` isolated on-disk cache | Multiple queries within a task share the cache; the directory can be reclaimed when the task finishes. |
| Attachment source | Knowledge-base pre-generated `.duckdb` only | Aligned with Claude Code; newly uploaded Excel/CSV files in a conversation do NOT go through this path. |

## Key Files

| File | Role |
|------|------|
| `shared/services/duckdb_query.py` | Shared `DuckDBQueryExecutor` (download / cache / READ_ONLY execution) |
| `executor/services/duckdb_query.py` | Thin re-export for backward compatibility |
| `chat_shell/chat_shell/services/duckdb_sandbox_runner.py` | Chat Shell process-level runner, manages cache per task_id |
| `chat_shell/chat_shell/tools/mcp/post_processors/base.py` | Generic MCP tool-result post-processor registry |
| `chat_shell/chat_shell/tools/mcp/post_processors/duckdb_post_processor.py` | DuckDB-specific post-processor |
| `chat_shell/chat_shell/tools/mcp/client.py` | `MCPClient` integrates the post-processor hook |
| `chat_shell/chat_shell/main.py` | Registers DuckDB post-processors during process startup |

## Data Flow

1. The AI calls MCP tool `wegent_data_query(attachment_id=42, sql="...")`.
2. The Backend returns:
   ```json
   {
     "success": true,
     "content_ref": { "url": "...", "auth_token": "..." },
     "tables": ["sales"],
     "sql": "SELECT ...",
     "instruction": "Download the .duckdb file ..."
   }
   ```
3. The `MCPClient` wrapper layer detects the registered post-processor and passes the result to `duckdb_post_processor._process_query`.
4. The post-processor:
   - Decodes the payload (supports `str` / `dict` / `(content, artifact)` MCP response shapes).
   - Calls `ChatShellDuckDBRunner.run_query(task_id, attachment_id, content_ref, sql)`.
   - Inside the runner:
     - If the `(task_id, attachment_id)` pair is not yet cached → download the `.duckdb` file via the ContentRef.
     - On a `:memory:` connection: `ATTACH '...' AS data_db (READ_ONLY)` → `SET enable_external_access = false` → execute SQL → truncate to `DUCKDB_MAX_ROWS`.
   - Merges the query result into the payload (`success`, `result`, `error`) and removes the `instruction` field.
5. The LLM sees a tool result that already contains the real rows.

## Configuration (Chat Shell)

All settings live in `chat_shell/chat_shell/core/config.py` and can be overridden via environment variables (prefix `CHAT_SHELL_`):

| Setting | Default | Description |
|---------|---------|-------------|
| `DUCKDB_ANALYSIS_ENABLED` | `true` | When disabled, no post-processor is registered and `wegent_data_query` falls back to the original ContentRef behavior. |
| `DUCKDB_QUERY_TIMEOUT` | `60.0` | Per-query execution timeout (seconds). |
| `DUCKDB_MAX_ROWS` | `5000` | Max rows returned per query (matches the Executor). |
| `DUCKDB_CACHE_DIR` | `/tmp/wegent_duckdb_cache` | Cache root directory; each task gets its own subdirectory. |

## Security and Fallback

- **READ_ONLY ATTACH**: all write operations (`DROP`, `DELETE`, `INSERT`, `UPDATE`, `CREATE`) are rejected by DuckDB.
- **`enable_external_access = false`**: disables DuckDB functions that can reach the filesystem / network, such as `read_csv_auto`, `read_parquet`, and `httpfs`.
- **Row truncation**: results larger than `DUCKDB_MAX_ROWS` are truncated; the response carries `truncated=true` and `total_count`.
- **Fallback strategy**: if the runner raises (download failure, DuckDB unavailable, etc.), the post-processor keeps the Backend's original response. The LLM can still explain the download steps to the user based on the instruction, so the conversation is never fully blocked.

## Tests

- `shared/tests/services/test_duckdb_query.py`: download, caching, READ_ONLY isolation, result schema.
- `chat_shell/tests/services/test_duckdb_runner.py`: task-scoped cache, failure handling.
- `chat_shell/tests/tools/mcp/post_processors/test_duckdb_post_processor.py`: payload decoding, SQL result merging, fallback logic.
- `executor/tests/services/test_duckdb_query.py`: retains the original coverage, validates both import paths via the shim.

## Parity with Claude Code

Chat Shell matches the Executor on the following dimensions:

1. **Same shared implementation**: `shared.services.duckdb_query.DuckDBQueryExecutor` is the single source of truth.
2. **Same security policy**: `READ_ONLY ATTACH` + `enable_external_access=false`.
3. **Same row cap**: default `max_rows=5000`, overridable via configuration.
4. **Same error structure**: `{"success": false, "error": "..."}`.
5. **Same success structure**: `{"success": true, "columns": [...], "rows": [...], "row_count": ..., "truncated": ..., "total_count": ...}`.

## Known Limitations

- **Does not support Excel/CSV files uploaded mid-conversation**: only knowledge-base pre-generated `.duckdb` attachments are handled. Raw files uploaded in a conversation still go through the existing text-extraction path, matching the Executor's behavior.
- **In-process execution inside Chat Shell**: unlike the Executor's Docker-level isolation, Chat Shell shares the main process. Security is guaranteed at the DuckDB connection layer, but if user-defined extension capabilities are introduced in the future, the isolation strategy must be re-evaluated.
