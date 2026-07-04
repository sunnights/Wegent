# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from llama_index.core import Document, SimpleDirectoryReader

from knowledge_engine.embedding.capabilities import embed_model_supports_image_input
from knowledge_engine.ingestion.excel_qa_unitizer import (
    EXCEL_FAQ_PARSER_SUBTYPE,
    ExcelFAQUnitizationResult,
    build_excel_qa_pair_nodes_from_binary,
    build_excel_qa_pair_nodes_from_file,
)
from knowledge_engine.ingestion.pipeline import (
    build_ingestion_result,
    prepare_ingestion,
)
from knowledge_engine.storage.base import BaseStorageBackend
from knowledge_engine.storage.chunk_metadata import ChunkMetadata
from knowledge_engine.text_sanitizer import sanitize_text_for_indexing
from shared.telemetry.decorators import add_span_event
from shared.utils.xmind_parser import parse_xmind_to_markdown

logger = logging.getLogger(__name__)

OPENPYXL_EXCEL_EXTENSIONS = {".xlsx", ".xlsm", ".xltx", ".xltm"}
SAFE_METADATA_KEYS = {
    "filename",
    "file_path",
    "file_name",
    "file_type",
    "file_size",
    "creation_date",
    "last_modified_date",
    "page_label",
    "page_number",
}


def sanitize_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = {}
    for key in SAFE_METADATA_KEYS:
        if key in metadata:
            value = metadata[key]
            if value is not None:
                sanitized[key] = str(value) if not isinstance(value, str) else value
    return sanitized


def sanitize_documents(
    documents: List[Document],
    *,
    sanitize_inline_images: bool,
) -> List[Document]:
    """Sanitize document text before chunking."""
    for doc in documents:
        result = sanitize_text_for_indexing(
            doc.text,
            sanitize_inline_images=sanitize_inline_images,
        )
        if result.replacements_count == 0:
            continue

        add_span_event(
            "rag.indexer.documents.sanitized",
            {
                "replacements_count": str(result.replacements_count),
                "replacement_summary": str(result.replacement_summary),
            },
        )
        doc.set_content(result.text)

    return documents


class DocumentIndexer:
    def __init__(
        self,
        storage_backend: BaseStorageBackend,
        embed_model,
        splitter_config: dict | None = None,
        file_extension: str | None = None,
    ):
        self.storage_backend = storage_backend
        self.embed_model = embed_model
        self.file_extension = file_extension
        ingestion_preparation = prepare_ingestion(
            splitter_config,
            file_extension=file_extension,
        )
        self.splitter_config = ingestion_preparation.normalized_splitter_config

    def index_document(
        self,
        file_path: str,
        chunk_metadata: ChunkMetadata,
        **kwargs,
    ) -> Dict:
        if (self.file_extension or "").lower() in OPENPYXL_EXCEL_EXTENSIONS:
            excel_result = build_excel_qa_pair_nodes_from_file(
                file_path,
                source_file=chunk_metadata.source_file,
            )
            if excel_result is not None and excel_result.detected:
                return self._index_prebuilt_nodes(
                    nodes=excel_result.nodes,
                    chunk_metadata=chunk_metadata,
                    parser_subtype=EXCEL_FAQ_PARSER_SUBTYPE,
                    excel_faq_result=excel_result,
                    **kwargs,
                )

        documents = SimpleDirectoryReader(input_files=[file_path]).load_data()
        return self._index_documents(
            documents=documents,
            chunk_metadata=chunk_metadata,
            **kwargs,
        )

    def index_from_binary(
        self,
        binary_data: bytes,
        file_extension: str,
        chunk_metadata: ChunkMetadata,
        **kwargs,
    ) -> Dict:
        normalized_extension = file_extension.lower()
        if normalized_extension in OPENPYXL_EXCEL_EXTENSIONS:
            excel_result = build_excel_qa_pair_nodes_from_binary(
                binary_data,
                source_file=chunk_metadata.source_file,
            )
            if excel_result is not None and excel_result.detected:
                return self._index_prebuilt_nodes(
                    nodes=excel_result.nodes,
                    chunk_metadata=chunk_metadata,
                    parser_subtype=EXCEL_FAQ_PARSER_SUBTYPE,
                    excel_faq_result=excel_result,
                    **kwargs,
                )

        # XMind files require special parsing: extract content.json from the ZIP
        # archive and convert the topic tree to Markdown before indexing.
        if normalized_extension == ".xmind":
            markdown_text = parse_xmind_to_markdown(binary_data)
            filename_without_ext = Path(chunk_metadata.source_file).stem
            documents = [
                Document(
                    text=markdown_text,
                    metadata={"filename": filename_without_ext},
                )
            ]
            return self._index_documents(
                documents=documents,
                chunk_metadata=chunk_metadata,
                **kwargs,
            )

        with tempfile.NamedTemporaryFile(
            suffix=file_extension,
            delete=False,
        ) as tmp_file:
            tmp_file.write(binary_data)
            tmp_file_path = tmp_file.name

        try:
            documents = SimpleDirectoryReader(input_files=[tmp_file_path]).load_data()
            filename_without_ext = Path(chunk_metadata.source_file).stem
            for doc in documents:
                doc.metadata["filename"] = filename_without_ext

            return self._index_documents(
                documents=documents,
                chunk_metadata=chunk_metadata,
                **kwargs,
            )
        finally:
            try:
                Path(tmp_file_path).unlink()
            except Exception as exc:
                logger.warning(
                    "Failed to delete temporary file %s: %s",
                    tmp_file_path,
                    exc,
                )

    def _index_documents(
        self,
        documents: List[Document],
        chunk_metadata: ChunkMetadata,
        **kwargs,
    ) -> Dict:
        add_span_event(
            "rag.indexer.documents.received",
            {
                "knowledge_id": chunk_metadata.knowledge_id,
                "doc_ref": chunk_metadata.doc_ref,
                "source_file": chunk_metadata.source_file,
                "document_count": str(len(documents)),
            },
        )

        for doc in documents:
            doc.metadata = sanitize_metadata(doc.metadata)

        documents = sanitize_documents(
            documents,
            sanitize_inline_images=not embed_model_supports_image_input(
                self.embed_model
            ),
        )

        ingestion_result = build_ingestion_result(
            documents=documents,
            splitter_config=self.splitter_config,
            file_extension=self.file_extension,
            embed_model=self.embed_model,
        )
        parser_subtype = ingestion_result.parser_subtype

        if ingestion_result.parent_nodes is not None:
            chunk_metadata.apply_to_nodes(ingestion_result.parent_nodes)
            self.storage_backend.save_parent_nodes(
                knowledge_id=chunk_metadata.knowledge_id,
                parent_nodes=ingestion_result.parent_nodes,
                **kwargs,
            )

        nodes = ingestion_result.index_nodes

        chunk_metadata.apply_to_nodes(nodes)

        add_span_event(
            "rag.indexer.documents.split",
            {
                "knowledge_id": chunk_metadata.knowledge_id,
                "doc_ref": chunk_metadata.doc_ref,
                "node_count": str(len(nodes)),
                "splitter_type": self.splitter_config.chunk_strategy,
            },
        )

        chunks_data = self._build_chunks_metadata(
            nodes,
            parser_subtype=parser_subtype,
        )
        result = self.storage_backend.index_with_metadata(
            nodes=nodes,
            chunk_metadata=chunk_metadata,
            embed_model=self.embed_model,
            **kwargs,
        )

        result.update(
            {
                "doc_ref": chunk_metadata.doc_ref,
                "knowledge_id": chunk_metadata.knowledge_id,
                "source_file": chunk_metadata.source_file,
                "chunk_count": len(nodes),
                "created_at": chunk_metadata.created_at,
                "chunks_data": chunks_data,
            }
        )
        return result

    def _index_prebuilt_nodes(
        self,
        *,
        nodes: List,
        chunk_metadata: ChunkMetadata,
        parser_subtype: str | None = None,
        excel_faq_result: ExcelFAQUnitizationResult | None = None,
        **kwargs,
    ) -> Dict:
        chunk_metadata.apply_to_nodes(nodes)

        add_span_event(
            "rag.indexer.prebuilt_nodes.received",
            {
                "knowledge_id": chunk_metadata.knowledge_id,
                "doc_ref": chunk_metadata.doc_ref,
                "source_file": chunk_metadata.source_file,
                "node_count": str(len(nodes)),
                "parser_subtype": parser_subtype or "",
            },
        )

        chunks_data = self._build_chunks_metadata(
            nodes,
            parser_subtype=parser_subtype,
            excel_faq_result=excel_faq_result,
        )
        result = self.storage_backend.index_with_metadata(
            nodes=nodes,
            chunk_metadata=chunk_metadata,
            embed_model=self.embed_model,
            **kwargs,
        )
        result.update(
            {
                "doc_ref": chunk_metadata.doc_ref,
                "knowledge_id": chunk_metadata.knowledge_id,
                "source_file": chunk_metadata.source_file,
                "chunk_count": len(nodes),
                "created_at": chunk_metadata.created_at,
                "chunks_data": chunks_data,
            }
        )
        return result

    def _build_chunks_metadata(
        self,
        nodes: List,
        *,
        parser_subtype: str | None = None,
        excel_faq_result: ExcelFAQUnitizationResult | None = None,
    ) -> Dict[str, Any]:
        items = []
        current_position = 0

        for idx, node in enumerate(nodes):
            text = node.text if hasattr(node, "text") else str(node)
            text_length = len(text)
            token_count = text_length // 4
            items.append(
                {
                    "index": idx,
                    "content": text,
                    "token_count": token_count,
                    "start_position": current_position,
                    "end_position": current_position + text_length,
                    "metadata": dict(getattr(node, "metadata", {}) or {}),
                }
            )
            current_position += text_length

        chunks_data = {
            "items": items,
            "total_count": len(items),
            "splitter_type": self.splitter_config.chunk_strategy,
            "splitter_subtype": parser_subtype,
            "qa_pair_count": len(items) if parser_subtype == "qa_pair" else 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if excel_faq_result is not None:
            chunks_data.update(
                {
                    "source_format": "excel_faq",
                    "excel_faq_detected": excel_faq_result.detected,
                    "excel_faq_confidence": excel_faq_result.confidence,
                    "excel_faq_sheet_count": len(excel_faq_result.sheet_summaries),
                    "excel_faq_qa_row_count": excel_faq_result.qa_row_count,
                    "excel_faq_skipped_row_count": excel_faq_result.skipped_row_count,
                }
            )
        return chunks_data
