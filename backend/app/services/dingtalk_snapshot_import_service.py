# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Import DingTalk documents as immutable-at-source Wegent snapshots."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.models.dingtalk_doc import DingtalkSyncedNode
from app.models.external_knowledge_snapshot import ExternalKnowledgeSnapshot
from app.models.knowledge import KnowledgeDocument
from app.models.user import User
from app.schemas.dingtalk_doc import (
    DingtalkSnapshotImportItem,
    DingtalkSnapshotImportResponse,
)
from app.schemas.knowledge import (
    DocumentSourceType,
    KnowledgeDocumentCreate,
)
from app.services.context import context_service
from app.services.dingtalk_doc_service import (
    DingTalkDocService,
    DingTalkMCPToolError,
)
from app.services.knowledge import KnowledgeService
from app.services.knowledge.orchestrator import knowledge_orchestrator

MCP_TOOL_GET_DOCUMENT_CONTENT = "get_document_content"
PROVIDER_DINGTALK = "dingtalk"


class DingTalkSnapshotImportService:
    """Fetch selected DingTalk content and write it into a Wegent KB."""

    @classmethod
    async def import_nodes(
        cls,
        db: Session,
        user: User,
        knowledge_base_id: int,
        node_ids: list[int],
    ) -> DingtalkSnapshotImportResponse:
        """Import documents under the selected nodes and queue their indexes."""
        cls._assert_target_writable(db, user.id, knowledge_base_id)
        nodes = cls._resolve_document_nodes(db, user.id, node_ids)

        mcp_url = DingTalkDocService.get_user_dingtalk_mcp_url(user)
        if not mcp_url:
            raise ValueError("DingTalk Docs MCP is not configured or enabled")

        contents = await cls._fetch_contents(mcp_url, nodes)
        items = [
            cls._store_snapshot(
                db=db,
                user=user,
                knowledge_base_id=knowledge_base_id,
                node=node,
                content=contents[node.id],
            )
            for node in nodes
        ]
        return DingtalkSnapshotImportResponse(
            knowledge_base_id=knowledge_base_id,
            created=sum(item.action == "created" for item in items),
            updated=sum(item.action == "updated" for item in items),
            items=items,
        )

    @staticmethod
    def _assert_target_writable(
        db: Session,
        user_id: int,
        knowledge_base_id: int,
    ) -> None:
        knowledge_base, has_access = KnowledgeService.get_knowledge_base(
            db=db,
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
        )
        if knowledge_base is None or not has_access:
            raise ValueError("Knowledge base not found or access denied")
        if not KnowledgeService.can_manage_knowledge_base_documents(
            db,
            knowledge_base_id,
            user_id,
        ):
            raise PermissionError("No permission to import into this knowledge base")

    @staticmethod
    def _resolve_document_nodes(
        db: Session,
        user_id: int,
        node_ids: list[int],
    ) -> list[DingtalkSyncedNode]:
        selected_ids = list(dict.fromkeys(node_ids))
        active_nodes = (
            db.query(DingtalkSyncedNode)
            .filter(
                DingtalkSyncedNode.user_id == user_id,
                DingtalkSyncedNode.is_active == True,  # noqa: E712
            )
            .all()
        )
        by_id = {node.id: node for node in active_nodes}
        missing_ids = [node_id for node_id in selected_ids if node_id not in by_id]
        if missing_ids:
            raise ValueError("One or more DingTalk nodes are unavailable")

        children: dict[tuple[str, str], list[DingtalkSyncedNode]] = defaultdict(list)
        for node in active_nodes:
            children[(node.source, node.parent_node_id)].append(node)

        documents: list[DingtalkSyncedNode] = []
        visited: set[tuple[str, str]] = set()

        def collect(node: DingtalkSyncedNode) -> None:
            key = (node.source, node.dingtalk_node_id)
            if key in visited:
                return
            visited.add(key)
            if node.node_type == "folder":
                for child in children.get(key, []):
                    collect(child)
                return
            documents.append(node)

        for node_id in selected_ids:
            collect(by_id[node_id])
        if not documents:
            raise ValueError("No importable DingTalk documents were selected")
        return documents

    @classmethod
    async def _fetch_contents(
        cls,
        mcp_url: str,
        nodes: list[DingtalkSyncedNode],
    ) -> dict[int, str]:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError:
            raise RuntimeError("MCP client is unavailable") from None

        contents: dict[int, str] = {}
        async with streamablehttp_client(url=mcp_url) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                for node in nodes:
                    result = await session.call_tool(
                        MCP_TOOL_GET_DOCUMENT_CONTENT,
                        {"nodeId": node.dingtalk_node_id},
                    )
                    contents[node.id] = cls._parse_content_result(result)
        return contents

    @classmethod
    def _parse_content_result(cls, result: Any) -> str:
        """Extract Markdown without depending on one DingTalk response envelope."""
        if getattr(result, "isError", False) is True:
            raise DingTalkMCPToolError(
                "DingTalk MCP get_document_content returned an error"
            )

        markdown_parts: list[str] = []
        for item in getattr(result, "content", []) or []:
            if getattr(item, "type", None) != "text":
                continue
            raw_text = (getattr(item, "text", "") or "").strip()
            if not raw_text:
                continue
            try:
                payload = json.loads(raw_text)
            except (json.JSONDecodeError, TypeError):
                markdown_parts.append(raw_text)
                continue
            extracted = cls._extract_markdown(payload)
            if extracted:
                markdown_parts.append(extracted)

        content = "\n\n".join(markdown_parts).strip()
        if not content:
            raise DingTalkMCPToolError("DingTalk MCP returned no document content")
        return content

    @classmethod
    def _extract_markdown(cls, value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if not isinstance(value, dict):
            return ""
        if value.get("success") is False:
            raise DingTalkMCPToolError(
                "DingTalk MCP get_document_content was unsuccessful"
            )
        for key in ("markdown", "content", "text", "data", "result"):
            extracted = cls._extract_markdown(value.get(key))
            if extracted:
                return extracted
        return ""

    @classmethod
    def _store_snapshot(
        cls,
        db: Session,
        user: User,
        knowledge_base_id: int,
        node: DingtalkSyncedNode,
        content: str,
    ) -> DingtalkSnapshotImportItem:
        external_resource_id = f"{node.source}:{node.dingtalk_node_id}"
        mapping = (
            db.query(ExternalKnowledgeSnapshot)
            .filter(
                ExternalKnowledgeSnapshot.knowledge_base_id == knowledge_base_id,
                ExternalKnowledgeSnapshot.provider == PROVIDER_DINGTALK,
                ExternalKnowledgeSnapshot.external_resource_id == external_resource_id,
            )
            .first()
        )
        document = None
        if mapping is not None:
            document = (
                db.query(KnowledgeDocument)
                .filter(
                    KnowledgeDocument.id == mapping.document_id,
                    KnowledgeDocument.kind_id == knowledge_base_id,
                )
                .first()
            )

        if document is not None:
            knowledge_orchestrator.update_document_content(
                db=db,
                user=user,
                document_id=document.id,
                content=content,
                trigger_reindex=True,
            )
            document.name = cls._document_name(node.name)
            mapping.source_url = node.doc_url
            db.commit()
            return DingtalkSnapshotImportItem(
                node_id=node.id,
                document_id=document.id,
                action="updated",
            )

        if mapping is not None:
            db.delete(mapping)
            db.flush()

        document_name = cls._document_name(node.name)
        binary_content = content.encode("utf-8")
        attachment, _ = context_service.upload_attachment(
            db=db,
            user_id=user.id,
            filename=f"{document_name}.md",
            binary_data=binary_content,
            subtask_id=0,
        )
        response = knowledge_orchestrator.create_document_from_attachment(
            db=db,
            user=user,
            knowledge_base_id=knowledge_base_id,
            data=KnowledgeDocumentCreate(
                attachment_id=attachment.id,
                name=document_name,
                file_extension="md",
                file_size=len(binary_content),
                source_type=DocumentSourceType.TEXT,
            ),
            trigger_indexing=True,
            trigger_summary=False,
        )
        db.add(
            ExternalKnowledgeSnapshot(
                knowledge_base_id=knowledge_base_id,
                provider=PROVIDER_DINGTALK,
                external_resource_id=external_resource_id,
                source_url=node.doc_url,
                document_id=response.id,
            )
        )
        db.commit()
        return DingtalkSnapshotImportItem(
            node_id=node.id,
            document_id=response.id,
            action="created",
        )

    @staticmethod
    def _document_name(name: str) -> str:
        normalized = re.sub(r"[\\/:*?\"<>|]+", "-", name).strip()
        if normalized.lower().endswith(".md"):
            normalized = normalized[:-3].rstrip()
        return (normalized or "DingTalk document")[:252]
