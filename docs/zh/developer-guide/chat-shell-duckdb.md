---
sidebar_position: 10
---

# Chat Shell DuckDB 数据分析集成

## 背景

Wegent 的 `wegent-data-analysis` Skill 原本仅支持 **Claude Code Shell**：AI 通过 Backend MCP 工具 `wegent_data_query` / `wegent_data_schema` 获取知识库预生成的 `.duckdb` 文件的 `ContentRef`，然后由 Executor 容器内的 `DuckDBQueryExecutor` 本地执行查询。

Chat Shell 作为轻量级对话引擎，直到本次改动之前并未接入该能力，对话场景中询问 Excel/CSV 数据只能返回 `ContentRef` 下载链接，用户体验不一致。

本文介绍 Chat Shell 如何在 **不修改 Backend、Skill、AI Prompt** 的前提下，透明地把 `wegent_data_query` 的 ContentRef + SQL 结果替换成真实查询结果返回给 LLM。

## 架构

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
 │    - 按 task_id 隔离缓存                                              │
 │    - 复用 shared.services.duckdb_query.DuckDBQueryExecutor            │
 │    - :memory: + ATTACH READ_ONLY + enable_external_access=false      │
 │                                                                      │
 └──────────────────────────────────────────────────────────────────────┘
          ▲                                                ▲
          │                                                │
          │ 复用共享模块                                   │ 下载 .duckdb（ContentRef）
          │                                                │
 ┌────────┴─────────────────┐              ┌───────────────┴──────────────┐
 │  Executor (ClaudeCode)   │              │  Backend                      │
 │  也使用                  │              │  - /internal/rag/content/{id} │
 │  shared.services.duckdb_ │              │  - duckdb_cache 表            │
 │  query                   │              └───────────────────────────────┘
 └──────────────────────────┘
```

### 关键设计决策

| 决策点 | 选择 | 原因 |
|--------|------|------|
| 执行位置 | Chat Shell 进程内 | `SandboxClient.execute()` 仅接受 prompt，不支持上传/执行代码；DuckDB 的安全性由连接层强制，无需容器隔离。 |
| 安全控制 | `ATTACH ... (READ_ONLY)` + `SET enable_external_access = false` | 与 Executor 等价，禁用写入和外部访问 |
| 触发机制 | MCP tool-result post-processor | 对 AI / Prompt / Skill / Backend 完全透明 |
| 共享代码 | `shared/services/duckdb_query.py` | Executor 与 Chat Shell 使用同一实现，保证结果一致 |
| 缓存策略 | 按 `task_id` 隔离的磁盘缓存 | 对话内多轮查询共享缓存，task 结束后可清理 |
| 附件来源 | 仅知识库预生成 `.duckdb` | 与 Claude Code 对齐；对话中新上传 Excel/CSV 不走此路径 |

## 关键文件

| 文件 | 作用 |
|------|------|
| `shared/services/duckdb_query.py` | 共享 `DuckDBQueryExecutor`（下载 / 缓存 / READ_ONLY 执行） |
| `executor/services/duckdb_query.py` | 向后兼容的薄 re-export |
| `chat_shell/chat_shell/services/duckdb_sandbox_runner.py` | Chat Shell 进程级 Runner，按 task_id 管理缓存 |
| `chat_shell/chat_shell/tools/mcp/post_processors/base.py` | 通用 MCP 工具结果 post-processor 注册表 |
| `chat_shell/chat_shell/tools/mcp/post_processors/duckdb_post_processor.py` | DuckDB 专用 post-processor |
| `chat_shell/chat_shell/tools/mcp/client.py` | `MCPClient` 集成 post-processor 钩子 |
| `chat_shell/chat_shell/main.py` | 进程启动时注册 DuckDB post-processors |

## 数据流

1. AI 调用 MCP 工具 `wegent_data_query(attachment_id=42, sql="...")`
2. Backend 返回
   ```json
   {
     "success": true,
     "content_ref": { "url": "...", "auth_token": "..." },
     "tables": ["sales"],
     "sql": "SELECT ...",
     "instruction": "Download the .duckdb file ..."
   }
   ```
3. `MCPClient` 包装层检测到注册的 post-processor，把结果交给 `duckdb_post_processor._process_query`
4. Post-processor：
   - 解析 payload（支持 `str` / `dict` / `(content, artifact)` 三种 MCP 响应形式）
   - 调用 `ChatShellDuckDBRunner.run_query(task_id, attachment_id, content_ref, sql)`
   - Runner 内：
     - 若该 `(task_id, attachment_id)` 未缓存 → 使用 ContentRef 下载 `.duckdb`
     - 在 `:memory:` 连接上 `ATTACH '...' AS data_db (READ_ONLY)` → `SET enable_external_access = false` → 执行 SQL → 拉取结果并截断到 `DUCKDB_MAX_ROWS`
   - 把查询结果 merge 进原 payload（`success`、`result`、`error`），并删除 `instruction` 字段
5. LLM 直接看到带真实行数据的 tool 结果。

## 配置项（Chat Shell）

所有配置位于 `chat_shell/chat_shell/core/config.py`，可通过环境变量覆盖（前缀 `CHAT_SHELL_`）：

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `DUCKDB_ANALYSIS_ENABLED` | `true` | 关闭后 post-processor 不会被注册，`wegent_data_query` 退回到原始 ContentRef 行为 |
| `DUCKDB_QUERY_TIMEOUT` | `60.0` | 单次查询执行超时（秒） |
| `DUCKDB_MAX_ROWS` | `5000` | 每次查询返回的最大行数（与 Executor 对齐） |
| `DUCKDB_CACHE_DIR` | `/tmp/wegent_duckdb_cache` | 缓存根目录；每个 task 一个子目录 |

## 安全与降级

- **READ_ONLY ATTACH**：所有写操作（`DROP`、`DELETE`、`INSERT`、`UPDATE`、`CREATE`）都会被 DuckDB 拒绝。
- **`enable_external_access = false`**：禁用 `read_csv_auto`、`read_parquet`、`httpfs` 等能访问文件系统 / 网络的 DuckDB 函数。
- **行数截断**：超过 `DUCKDB_MAX_ROWS` 的结果会被截断，响应中含 `truncated=true` 与 `total_count`。
- **降级策略**：若 runner 抛错（下载失败、DuckDB 不可用等），post-processor 会保留 Backend 原始响应，LLM 仍可基于 instruction 向用户解释下载步骤，不会完全阻塞对话。

## 测试

- `shared/tests/services/test_duckdb_query.py`：下载、缓存、READ_ONLY 隔离、结果 schema
- `chat_shell/tests/services/test_duckdb_runner.py`：task-scoped 缓存、失败处理
- `chat_shell/tests/tools/mcp/post_processors/test_duckdb_post_processor.py`：payload 解码、SQL 结果 merge、降级逻辑
- `executor/tests/services/test_duckdb_query.py`：保留原测试覆盖，通过 shim 导入验证双路径

## 与 Claude Code 的一致性

Chat Shell 与 Executor 在以下维度达到了行为一致：

1. **相同的共享实现**：`shared.services.duckdb_query.DuckDBQueryExecutor` 是唯一事实源头。
2. **相同的安全策略**：`READ_ONLY ATTACH` + `enable_external_access=false`。
3. **相同的行数限制**：默认 `max_rows=5000`，可由配置覆盖。
4. **相同的错误结构**：`{"success": false, "error": "..."}`。
5. **相同的成功结构**：`{"success": true, "columns": [...], "rows": [...], "row_count": ..., "truncated": ..., "total_count": ...}`。

## 已知限制

- **不支持对话中直接上传的 Excel/CSV**：仅处理知识库预生成的 `.duckdb` 附件。对话内上传的原始文件仍走既有的文本抽取逻辑，与 Executor 行为一致。
- **Chat Shell 进程内执行**：与 Executor 的 Docker 容器级隔离相比，Chat Shell 复用主进程。安全性由 DuckDB 连接层保证，但如果在未来引入用户自定义扩展能力，需要重新评估隔离策略。
