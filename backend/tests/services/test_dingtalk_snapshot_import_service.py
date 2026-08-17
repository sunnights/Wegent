# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for DingTalk snapshot import."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.dingtalk_doc import DingtalkSyncedNode
from app.models.user import User
from app.services.dingtalk_doc_service import DingTalkMCPToolError
from app.services.dingtalk_snapshot_import_service import (
    DingTalkSnapshotImportService,
)


def _text_result(text: str, *, is_error: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        isError=is_error,
        content=[SimpleNamespace(type="text", text=text)],
    )


def _node(
    user_id: int,
    external_id: str,
    *,
    node_type: str,
    parent_id: str = "",
) -> DingtalkSyncedNode:
    return DingtalkSyncedNode(
        user_id=user_id,
        dingtalk_node_id=external_id,
        name=external_id,
        doc_url=f"https://alidocs.dingtalk.com/i/nodes/{external_id}",
        parent_node_id=parent_id,
        node_type=node_type,
        workspace_id="",
        source="docs",
        content_type="ALIDOC",
        content_updated_at=datetime.now(),
        is_active=True,
        last_synced_at=datetime.now(),
    )


def test_parse_content_result_accepts_plain_markdown() -> None:
    result = DingTalkSnapshotImportService._parse_content_result(
        _text_result("# Title\n\nBody")
    )

    assert result == "# Title\n\nBody"


def test_parse_content_result_accepts_json_envelope() -> None:
    result = DingTalkSnapshotImportService._parse_content_result(
        _text_result('{"success": true, "data": {"markdown": "# Title"}}')
    )

    assert result == "# Title"


def test_parse_content_result_rejects_provider_error() -> None:
    with pytest.raises(DingTalkMCPToolError):
        DingTalkSnapshotImportService._parse_content_result(
            _text_result("failed", is_error=True)
        )


def test_resolve_document_nodes_expands_folder_and_deduplicates(
    test_db: Session,
    test_user: User,
) -> None:
    folder = _node(test_user.id, "folder", node_type="folder")
    child = _node(
        test_user.id,
        "child",
        node_type="doc",
        parent_id="folder",
    )
    nested_folder = _node(
        test_user.id,
        "nested",
        node_type="folder",
        parent_id="folder",
    )
    nested_child = _node(
        test_user.id,
        "nested-child",
        node_type="doc",
        parent_id="nested",
    )
    test_db.add_all([folder, child, nested_folder, nested_child])
    test_db.commit()

    result = DingTalkSnapshotImportService._resolve_document_nodes(
        test_db,
        test_user.id,
        [folder.id, child.id],
    )

    assert [node.id for node in result] == [child.id, nested_child.id]


def test_resolve_document_nodes_rejects_another_users_node(
    test_db: Session,
    test_user: User,
) -> None:
    other = _node(test_user.id + 1, "other", node_type="doc")
    test_db.add(other)
    test_db.commit()

    with pytest.raises(ValueError, match="unavailable"):
        DingTalkSnapshotImportService._resolve_document_nodes(
            test_db,
            test_user.id,
            [other.id],
        )


def test_store_snapshot_updates_existing_document_without_replacing_creator() -> None:
    db = MagicMock()
    mapping = SimpleNamespace(document_id=19, source_url="old")
    document = SimpleNamespace(id=19, kind_id=8, name="Old", user_id=3)
    db.query.return_value.filter.return_value.first.side_effect = [mapping, document]
    user = SimpleNamespace(id=7)
    node = SimpleNamespace(
        id=4,
        source="docs",
        dingtalk_node_id="doc-4",
        doc_url="https://alidocs.dingtalk.com/i/nodes/doc-4",
        name="New title",
    )

    with patch(
        "app.services.dingtalk_snapshot_import_service.knowledge_orchestrator.update_document_content"
    ) as update_content:
        result = DingTalkSnapshotImportService._store_snapshot(
            db=db,
            user=user,
            knowledge_base_id=8,
            node=node,
            content="# New",
        )

    update_content.assert_called_once_with(
        db=db,
        user=user,
        document_id=19,
        content="# New",
        trigger_reindex=True,
    )
    assert document.user_id == 3
    assert document.name == "New title"
    assert mapping.source_url == node.doc_url
    assert result.action == "updated"


def test_store_snapshot_creates_document_as_initiating_user() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    user = SimpleNamespace(id=7)
    node = SimpleNamespace(
        id=4,
        source="docs",
        dingtalk_node_id="doc-4",
        doc_url="https://alidocs.dingtalk.com/i/nodes/doc-4",
        name="Design",
    )
    attachment = SimpleNamespace(id=12)

    with (
        patch(
            "app.services.dingtalk_snapshot_import_service.context_service.upload_attachment",
            return_value=(attachment, None),
        ),
        patch(
            "app.services.dingtalk_snapshot_import_service.KnowledgeService.create_document_record",
            return_value=SimpleNamespace(id=19),
        ) as create_document,
        patch(
            "app.services.dingtalk_snapshot_import_service.knowledge_orchestrator.reindex_document"
        ) as reindex_document,
    ):
        result = DingTalkSnapshotImportService._store_snapshot(
            db=db,
            user=user,
            knowledge_base_id=8,
            node=node,
            content="# Design",
        )

    assert create_document.call_args.kwargs["user_id"] == user.id
    assert create_document.call_args.kwargs["data"].attachment_id == 12
    mapping = db.add.call_args.args[0]
    assert mapping.external_resource_id == "docs:doc-4"
    assert mapping.source_url == node.doc_url
    assert mapping.document_id == 19
    reindex_document.assert_called_once_with(
        db=db,
        user=user,
        document_id=19,
        trigger_summary=False,
    )
    assert result.action == "created"


@pytest.mark.asyncio
async def test_import_nodes_recovers_from_concurrent_snapshot_creation() -> None:
    db = MagicMock()
    node = SimpleNamespace(
        id=4,
        source="docs",
        dingtalk_node_id="doc-4",
        doc_url="https://alidocs.dingtalk.com/i/nodes/doc-4",
        name="Design",
    )
    winner_mapping = SimpleNamespace(document_id=23, source_url="old")
    winner_document = SimpleNamespace(id=23, kind_id=8, name="Old", user_id=6)
    db.query.return_value.filter.return_value.first.side_effect = [
        None,
        winner_mapping,
        winner_document,
    ]
    db.commit.side_effect = [
        IntegrityError("INSERT", {}, RuntimeError("duplicate resource")),
        None,
    ]
    user = SimpleNamespace(id=7)
    attachment = SimpleNamespace(id=12)

    with (
        patch.object(DingTalkSnapshotImportService, "_assert_target_writable"),
        patch.object(
            DingTalkSnapshotImportService,
            "_resolve_document_nodes",
            return_value=[node],
        ),
        patch.object(
            DingTalkSnapshotImportService,
            "_fetch_contents",
            return_value={4: "# Design"},
        ),
        patch(
            "app.services.dingtalk_snapshot_import_service.DingTalkDocService.get_user_dingtalk_mcp_url",
            return_value="https://mcp.example.test",
        ),
        patch(
            "app.services.dingtalk_snapshot_import_service.context_service.upload_attachment",
            return_value=(attachment, None),
        ),
        patch(
            "app.services.dingtalk_snapshot_import_service.KnowledgeService.create_document_record",
            return_value=SimpleNamespace(id=19),
        ),
        patch(
            "app.services.dingtalk_snapshot_import_service.knowledge_orchestrator.update_document_content"
        ) as update_content,
        patch(
            "app.services.dingtalk_snapshot_import_service.knowledge_orchestrator.reindex_document"
        ) as reindex_document,
    ):
        result = await DingTalkSnapshotImportService.import_nodes(
            db=db,
            user=user,
            knowledge_base_id=8,
            node_ids=[4],
        )

    assert result.created == 0
    assert result.updated == 1
    assert result.items[0].document_id == 23
    db.rollback.assert_called_once()
    update_content.assert_called_once_with(
        db=db,
        user=user,
        document_id=23,
        content="# Design",
        trigger_reindex=True,
    )
    reindex_document.assert_not_called()
