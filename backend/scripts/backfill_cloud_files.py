#!/usr/bin/env python
# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Backfill cloud drive indexes from recent attachment contexts."""

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.knowledge import KnowledgeDocument
from app.models.subtask_context import ContextType, SubtaskContext
from app.services.cloud_file_service import cloud_file_service


def infer_source_type(db: Session, context: SubtaskContext) -> str:
    """Infer the best-effort cloud drive source type for an attachment."""
    knowledge_doc = (
        db.query(KnowledgeDocument.id)
        .filter(KnowledgeDocument.attachment_id == context.id)
        .first()
    )
    if knowledge_doc:
        return "knowledge"
    if context.subtask_id and context.subtask_id > 0:
        return "chat"
    return "unknown"


def backfill(days: int, limit: int | None, batch_size: int, dry_run: bool) -> int:
    """Backfill recent attachment contexts."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    processed = 0
    db = SessionLocal()
    try:
        query = (
            db.query(SubtaskContext)
            .filter(
                SubtaskContext.context_type == ContextType.ATTACHMENT.value,
                SubtaskContext.created_at >= cutoff,
            )
            .order_by(SubtaskContext.id.asc())
        )
        if limit:
            query = query.limit(limit)

        for context in query.yield_per(batch_size):
            source_type = infer_source_type(db, context)
            processed += 1
            if dry_run:
                print(
                    f"DRY-RUN attachment_id={context.id} user_id={context.user_id} "
                    f"source_type={source_type} name={context.name}"
                )
                continue
            cloud_file_service.record_attachment_created(
                db=db,
                context=context,
                source_type=source_type,
                source_ref={"backfilled": True},
            )
        return processed
    finally:
        db.close()


def main() -> None:
    """Parse arguments and run the backfill."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    count = backfill(args.days, args.limit, args.batch_size, args.dry_run)
    print(f"Processed {count} attachment contexts")


if __name__ == "__main__":
    main()
