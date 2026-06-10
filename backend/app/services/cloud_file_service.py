# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Cloud drive service built on top of attachment contexts."""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.cloud_file import CloudFile, CloudFileSourceType
from app.models.subtask_context import ContextStatus, ContextType, SubtaskContext
from app.models.user import User
from app.schemas.cloud_file import (
    CloudFileImportItem,
    CloudFileImportToKnowledgeResponse,
    CloudFileListResponse,
    CloudFileResponse,
    CloudFileStatsResponse,
)
from app.schemas.subtask_context import AttachmentResponse
from app.services.context import context_service
from app.services.knowledge import knowledge_orchestrator

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "bmp", "webp"}
DOCUMENT_EXTENSIONS = {"doc", "docx", "xmind"}
SPREADSHEET_EXTENSIONS = {"xls", "xlsx", "csv"}
PRESENTATION_EXTENSIONS = {"ppt", "pptx"}
TEXT_EXTENSIONS = {
    "txt",
    "md",
    "markdown",
    "json",
    "yaml",
    "yml",
    "xml",
    "html",
    "css",
    "js",
    "ts",
    "py",
}
VIDEO_EXTENSIONS = {"mp4", "avi", "mkv", "mov", "flv", "wmv"}
AUDIO_EXTENSIONS = {"mp3", "wav", "m4a", "aac", "ogg"}


class CloudFileService:
    """Manage cloud drive indexes without owning attachment binary data."""

    def record_attachment_created(
        self,
        db: Session,
        context: SubtaskContext,
        source_type: CloudFileSourceType | str = CloudFileSourceType.UNKNOWN,
        source_ref: Optional[Dict[str, Any]] = None,
    ) -> Optional[CloudFile]:
        """Create or update the cloud drive index for an attachment."""
        if context.context_type != ContextType.ATTACHMENT.value:
            return None
        if not context.user_id:
            return None

        normalized_source_type = self._normalize_source_type(source_type)
        existing = self._get_by_attachment(db, context.user_id, context.id)
        if existing:
            self._refresh_snapshot(existing, context)
            if existing.source_type in ("", CloudFileSourceType.UNKNOWN.value):
                existing.source_type = normalized_source_type
            existing.source_ref = self._merge_source_ref(
                existing.source_ref, source_ref
            )
            db.commit()
            db.refresh(existing)
            return existing

        cloud_file = CloudFile(
            user_id=context.user_id,
            attachment_id=context.id,
            display_name=context.original_filename or context.name,
            file_extension=context.file_extension or "",
            mime_type=context.mime_type or "",
            file_size=context.file_size or 0,
            source_type=normalized_source_type,
            source_ref=source_ref or {},
        )
        db.add(cloud_file)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return self._get_by_attachment(db, context.user_id, context.id)

        db.refresh(cloud_file)
        return cloud_file

    def list_files(
        self,
        db: Session,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        query: Optional[str] = None,
        source_type: Optional[str] = None,
        file_type: str = "all",
        sort: str = "created_desc",
    ) -> CloudFileListResponse:
        """Return a paginated visible cloud file list for one user."""
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        base_query = self._visible_query(db, user_id)
        base_query = base_query.join(
            SubtaskContext, CloudFile.attachment_id == SubtaskContext.id
        )

        if query:
            pattern = f"%{query.strip()}%"
            base_query = base_query.filter(
                or_(
                    CloudFile.display_name.ilike(pattern),
                    SubtaskContext.name.ilike(pattern),
                )
            )
        if source_type:
            base_query = base_query.filter(CloudFile.source_type == source_type)
        base_query = self._apply_file_type_filter(base_query, file_type)

        total = base_query.count()
        rows = (
            self._apply_sort(base_query, sort)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return CloudFileListResponse(
            items=[
                self._to_response(cloud_file, attachment)
                for cloud_file, attachment in rows
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_stats(self, db: Session, user_id: int) -> CloudFileStatsResponse:
        """Return count and total byte size for visible files."""
        total_count, total_size = (
            db.query(
                func.count(CloudFile.id),
                func.coalesce(func.sum(CloudFile.file_size), 0),
            )
            .filter(CloudFile.user_id == user_id, CloudFile.is_deleted.is_(False))
            .one()
        )
        return CloudFileStatsResponse(total_count=total_count, total_size=total_size)

    def soft_delete(self, db: Session, file_id: int, user_id: int) -> None:
        """Soft-delete only the cloud drive index."""
        cloud_file = self._get_visible_file(db, file_id, user_id)
        cloud_file.is_deleted = True
        cloud_file.deleted_at = datetime.now(timezone.utc)
        db.commit()

    def copy_to_attachment(
        self, db: Session, file_id: int, user_id: int
    ) -> AttachmentResponse:
        """Copy a cloud file into a new unlinked attachment."""
        cloud_file, attachment = self._get_visible_file_with_attachment(
            db, file_id, user_id
        )
        copied = context_service.copy_attachment_for_user(
            db=db,
            source_context=attachment,
            target_user_id=user_id,
            source_metadata={
                "cloud_file_source_id": cloud_file.id,
                "source": "cloud_drive",
            },
        )
        return AttachmentResponse.from_context(copied)

    def import_to_knowledge(
        self,
        db: Session,
        user: User,
        knowledge_base_id: int,
        file_ids: Iterable[int],
        folder_id: int = 0,
        splitter_config: Optional[Dict[str, Any]] = None,
    ) -> CloudFileImportToKnowledgeResponse:
        """Copy cloud files into a knowledge base as independent documents."""
        items: list[CloudFileImportItem] = []
        for file_id in file_ids:
            try:
                cloud_file, attachment = self._get_visible_file_with_attachment(
                    db, file_id, user.id
                )
                if attachment.status != ContextStatus.READY.value:
                    raise ValueError("Only ready files can be imported")
                if self._is_video_attachment(attachment):
                    raise ValueError(
                        "Video attachments cannot be imported into knowledge base"
                    )

                document = knowledge_orchestrator.create_document_with_content(
                    db=db,
                    user=user,
                    knowledge_base_id=knowledge_base_id,
                    name=cloud_file.display_name,
                    source_type="attachment",
                    attachment_id=attachment.id,
                    folder_id=folder_id,
                    splitter_config=splitter_config,
                )
                imported_attachment_id = document.attachment_id
                self._append_import_ref(
                    db=db,
                    cloud_file=cloud_file,
                    knowledge_base_id=knowledge_base_id,
                    document_id=document.id,
                    imported_attachment_id=imported_attachment_id,
                )
                items.append(
                    CloudFileImportItem(
                        cloud_file_id=file_id,
                        status="success",
                        document_id=document.id,
                        attachment_id=imported_attachment_id,
                    )
                )
            except Exception as exc:
                db.rollback()
                items.append(
                    CloudFileImportItem(
                        cloud_file_id=file_id,
                        status="failed",
                        error=str(exc),
                    )
                )

        success_count = sum(1 for item in items if item.status == "success")
        return CloudFileImportToKnowledgeResponse(
            success_count=success_count,
            failed_count=len(items) - success_count,
            items=items,
        )

    def _get_by_attachment(
        self, db: Session, user_id: int, attachment_id: int
    ) -> Optional[CloudFile]:
        return (
            db.query(CloudFile)
            .filter(
                CloudFile.user_id == user_id, CloudFile.attachment_id == attachment_id
            )
            .first()
        )

    def _visible_query(self, db: Session, user_id: int):
        return db.query(CloudFile, SubtaskContext).filter(
            CloudFile.user_id == user_id,
            CloudFile.is_deleted.is_(False),
            SubtaskContext.context_type == ContextType.ATTACHMENT.value,
        )

    def _get_visible_file(self, db: Session, file_id: int, user_id: int) -> CloudFile:
        cloud_file = (
            db.query(CloudFile)
            .filter(
                CloudFile.id == file_id,
                CloudFile.user_id == user_id,
                CloudFile.is_deleted.is_(False),
            )
            .first()
        )
        if not cloud_file:
            raise ValueError("Cloud file not found")
        return cloud_file

    def _get_visible_file_with_attachment(
        self, db: Session, file_id: int, user_id: int
    ) -> tuple[CloudFile, SubtaskContext]:
        row = (
            self._visible_query(db, user_id)
            .filter(
                CloudFile.id == file_id, CloudFile.attachment_id == SubtaskContext.id
            )
            .first()
        )
        if not row:
            raise ValueError("Cloud file not found")
        cloud_file, attachment = row
        if attachment.user_id != user_id:
            raise ValueError("Cloud file not found")
        return cloud_file, attachment

    def _refresh_snapshot(self, cloud_file: CloudFile, context: SubtaskContext) -> None:
        cloud_file.display_name = context.original_filename or context.name
        cloud_file.file_extension = context.file_extension or ""
        cloud_file.mime_type = context.mime_type or ""
        cloud_file.file_size = context.file_size or 0

    def _merge_source_ref(
        self, existing: Optional[Dict[str, Any]], incoming: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if not incoming:
            return existing or {}
        return {**(existing or {}), **incoming}

    def _append_import_ref(
        self,
        db: Session,
        cloud_file: CloudFile,
        knowledge_base_id: int,
        document_id: int,
        imported_attachment_id: Optional[int],
    ) -> None:
        source_ref = dict(cloud_file.source_ref or {})
        imports = list(source_ref.get("imports") or [])
        imports.append(
            {
                "type": "knowledge",
                "knowledge_base_id": knowledge_base_id,
                "document_id": document_id,
                "imported_attachment_id": imported_attachment_id,
                "imported_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        source_ref["imports"] = imports
        cloud_file.source_ref = source_ref
        db.commit()

    def _to_response(
        self, cloud_file: CloudFile, attachment: SubtaskContext
    ) -> CloudFileResponse:
        return CloudFileResponse(
            id=cloud_file.id,
            user_id=cloud_file.user_id,
            attachment_id=cloud_file.attachment_id,
            display_name=attachment.original_filename or cloud_file.display_name,
            file_extension=attachment.file_extension or cloud_file.file_extension or "",
            mime_type=attachment.mime_type or cloud_file.mime_type or "",
            file_size=attachment.file_size or cloud_file.file_size or 0,
            source_type=cloud_file.source_type,
            source_ref=cloud_file.source_ref or {},
            status=attachment.status,
            text_length=attachment.text_length or 0,
            created_at=cloud_file.created_at,
            updated_at=cloud_file.updated_at,
        )

    def _apply_sort(self, query, sort: str):
        sort_map = {
            "created_asc": CloudFile.created_at.asc(),
            "name_asc": CloudFile.display_name.asc(),
            "name_desc": CloudFile.display_name.desc(),
            "size_asc": CloudFile.file_size.asc(),
            "size_desc": CloudFile.file_size.desc(),
        }
        return query.order_by(sort_map.get(sort, CloudFile.created_at.desc()))

    def _apply_file_type_filter(self, query, file_type: str):
        if not file_type or file_type == "all":
            return query
        groups = {
            "image": IMAGE_EXTENSIONS,
            "document": DOCUMENT_EXTENSIONS,
            "spreadsheet": SPREADSHEET_EXTENSIONS,
            "presentation": PRESENTATION_EXTENSIONS,
            "text": TEXT_EXTENSIONS,
            "video": VIDEO_EXTENSIONS,
            "audio": AUDIO_EXTENSIONS,
            "pdf": {"pdf"},
        }
        extensions = groups.get(file_type)
        if extensions:
            return query.filter(func.lower(CloudFile.file_extension).in_(extensions))
        known = set().union(*groups.values())
        return query.filter(
            and_(
                CloudFile.file_extension.isnot(None),
                ~func.lower(CloudFile.file_extension).in_(known),
            )
        )

    def _is_video_attachment(self, attachment: SubtaskContext) -> bool:
        extension = (attachment.file_extension or "").lower().lstrip(".")
        mime_type = (attachment.mime_type or "").lower()
        return extension in VIDEO_EXTENSIONS or mime_type.startswith("video/")

    def _normalize_source_type(self, source_type: CloudFileSourceType | str) -> str:
        try:
            return CloudFileSourceType(source_type).value
        except ValueError:
            return CloudFileSourceType.UNKNOWN.value


cloud_file_service = CloudFileService()
