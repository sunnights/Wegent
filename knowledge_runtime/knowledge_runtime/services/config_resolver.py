# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Config resolver for knowledge_runtime.

Resolves full runtime configuration from the database by knowledge_base_id
reference, eliminating the need for Backend to transmit sensitive credentials
and configuration in HTTP requests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from knowledge_runtime.models.knowledge_document import KnowledgeDocument
from shared.models.db.kind import Kind
from shared.models.db.user import User
from shared.models.runtime_config import (
    RuntimeEmbeddingModelConfig,
    RuntimeRetrievalConfig,
    RuntimeRetrieverConfig,
)
from shared.utils.crypto import decrypt_api_key
from shared.utils.placeholder import process_custom_headers_placeholders

logger = logging.getLogger(__name__)

# Internal constants
DEFAULT_INDEX_FAMILIES = ["chunk_vector"]
DEFAULT_ENABLED_INDEX_FAMILIES = ["chunk_vector"]
DEFAULT_RETRIEVAL_POLICY = "chunk_only"


@dataclass
class IndexResolvedConfig:
    """Resolved configuration for document indexing."""

    index_owner_user_id: int
    retriever_config: RuntimeRetrieverConfig
    embedding_model_config: RuntimeEmbeddingModelConfig
    splitter_config: dict[str, Any] = field(default_factory=dict)
    index_families: list[str] = field(default_factory=lambda: ["chunk_vector"])
    user_name: str | None = None


@dataclass
class QueryResolvedConfig:
    """Resolved configuration for querying a single knowledge base."""

    knowledge_base_id: int
    index_owner_user_id: int
    retriever_config: RuntimeRetrieverConfig
    embedding_model_config: RuntimeEmbeddingModelConfig
    retrieval_config: RuntimeRetrievalConfig
    user_name: str | None = None


@dataclass
class AdminResolvedConfig:
    """Resolved configuration for admin operations (delete/purge/drop/list)."""

    index_owner_user_id: int
    retriever_config: RuntimeRetrieverConfig


class KnowledgeRuntimeConfigResolver:
    """Resolves full runtime config from database by knowledge_base_id reference.

    Resolution chain for each operation:
    1. Query kinds (kind="KnowledgeBase", id=knowledge_base_id) -> kb record
    2. index_owner_user_id = kb.user_id (never from request params)
    3. Extract retrievalConfig from kb.json.spec -> retriever_name, embedding refs, retrieval params
    4. Query kinds (kind="Retriever", name, namespace, user_id) -> RuntimeRetrieverConfig
    5. Query kinds (kind="Model", name, namespace, user_id) -> RuntimeEmbeddingModelConfig
    6. Query knowledge_documents (document_id) -> splitter_config (default if None)
    7. Query users (user_id) -> user_name (for embedding custom_headers)
    8. Decrypt API keys in storage_config and embedding config
    9. Process custom_headers placeholders with user_name
    """

    def resolve_index_config(
        self,
        db: Session,
        *,
        knowledge_base_id: int,
        document_id: int | None,
        user_id: int | None,
    ) -> IndexResolvedConfig:
        """Resolve all config needed for indexing from DB.

        Args:
            db: Database session.
            knowledge_base_id: Knowledge base ID (core reference).
            document_id: Optional document ID for splitter_config lookup.
            user_id: Optional requester user_id for user_name lookup.

        Returns:
            Fully resolved index configuration.

        Raises:
            ValueError: If knowledge base or required resources not found.
        """
        kb = self._get_knowledge_base(db, knowledge_base_id)
        index_owner_user_id = kb.user_id
        retrieval_config_spec = self._extract_retrieval_config_spec(kb)

        # Resolve retriever
        retriever_config = self._build_resolved_retriever_config(
            db=db,
            user_id=index_owner_user_id,
            name=retrieval_config_spec["retriever_name"],
            namespace=retrieval_config_spec["retriever_namespace"],
        )

        # Resolve user_name for custom_headers
        user_name = self._get_user_name(db, user_id)

        # Resolve embedding model
        embedding_model_config = self._build_resolved_embedding_model_config(
            db=db,
            user_id=index_owner_user_id,
            model_name=retrieval_config_spec["embedding_model_name"],
            model_namespace=retrieval_config_spec["embedding_model_namespace"],
            user_name=user_name,
        )

        # Resolve splitter_config from document
        splitter_config = self._get_splitter_config(db, document_id)

        return IndexResolvedConfig(
            index_owner_user_id=index_owner_user_id,
            retriever_config=retriever_config,
            embedding_model_config=embedding_model_config,
            splitter_config=splitter_config,
            index_families=DEFAULT_INDEX_FAMILIES,
            user_name=user_name,
        )

    def resolve_query_configs(
        self,
        db: Session,
        *,
        knowledge_base_ids: list[int],
        user_id: int | None,
    ) -> list[QueryResolvedConfig]:
        """Resolve all config needed for querying, one per KB.

        Args:
            db: Database session.
            knowledge_base_ids: List of knowledge base IDs to query.
            user_id: Optional requester user_id for user_name lookup.

        Returns:
            List of resolved query configurations.

        Raises:
            ValueError: If any knowledge base or required resources not found.
        """
        configs: list[QueryResolvedConfig] = []
        for kb_id in knowledge_base_ids:
            kb = self._get_knowledge_base(db, kb_id)
            index_owner_user_id = kb.user_id
            retrieval_config_spec = self._extract_retrieval_config_spec(kb)

            # Resolve retriever
            retriever_config = self._build_resolved_retriever_config(
                db=db,
                user_id=index_owner_user_id,
                name=retrieval_config_spec["retriever_name"],
                namespace=retrieval_config_spec["retriever_namespace"],
            )

            # Resolve user_name
            user_name = self._get_user_name(db, user_id)

            # Resolve embedding model
            embedding_model_config = self._build_resolved_embedding_model_config(
                db=db,
                user_id=index_owner_user_id,
                model_name=retrieval_config_spec["embedding_model_name"],
                model_namespace=retrieval_config_spec["embedding_model_namespace"],
                user_name=user_name,
            )

            # Build retrieval config from KB spec
            runtime_retrieval_config = RuntimeRetrievalConfig(
                top_k=retrieval_config_spec.get("top_k", 20),
                score_threshold=retrieval_config_spec.get("score_threshold", 0.7),
                retrieval_mode=retrieval_config_spec.get("retrieval_mode", "vector"),
                vector_weight=(
                    retrieval_config_spec.get("hybrid_weights", {}).get("vector_weight")
                    if retrieval_config_spec.get("retrieval_mode") == "hybrid"
                    else None
                ),
                keyword_weight=(
                    retrieval_config_spec.get("hybrid_weights", {}).get("keyword_weight")
                    if retrieval_config_spec.get("retrieval_mode") == "hybrid"
                    else None
                ),
            )

            configs.append(
                QueryResolvedConfig(
                    knowledge_base_id=kb_id,
                    index_owner_user_id=index_owner_user_id,
                    retriever_config=retriever_config,
                    embedding_model_config=embedding_model_config,
                    retrieval_config=runtime_retrieval_config,
                    user_name=user_name,
                )
            )
        return configs

    def resolve_admin_config(
        self,
        db: Session,
        *,
        knowledge_base_id: int,
    ) -> AdminResolvedConfig:
        """Resolve config for admin operations (delete/purge/drop/list).

        Only resolves retriever_config (sufficient for admin operations).

        Args:
            db: Database session.
            knowledge_base_id: Knowledge base ID.

        Returns:
            Admin configuration with retriever_config and index_owner_user_id.

        Raises:
            ValueError: If knowledge base or required resources not found.
        """
        kb = self._get_knowledge_base(db, knowledge_base_id)
        index_owner_user_id = kb.user_id
        retrieval_config_spec = self._extract_retrieval_config_spec(kb)

        retriever_config = self._build_resolved_retriever_config(
            db=db,
            user_id=index_owner_user_id,
            name=retrieval_config_spec["retriever_name"],
            namespace=retrieval_config_spec["retriever_namespace"],
        )

        return AdminResolvedConfig(
            index_owner_user_id=index_owner_user_id,
            retriever_config=retriever_config,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_knowledge_base(self, db: Session, knowledge_base_id: int) -> Kind:
        """Query KnowledgeBase Kind record by ID."""
        kb = (
            db.query(Kind)
            .filter(
                Kind.id == knowledge_base_id,
                Kind.kind == "KnowledgeBase",
                Kind.is_active.is_(True),
            )
            .first()
        )
        if kb is None:
            raise ValueError(f"Knowledge base {knowledge_base_id} not found")
        return kb

    def _extract_retrieval_config_spec(self, kb: Kind) -> dict[str, Any]:
        """Extract retrieval config spec from KB Kind record."""
        spec = (kb.json or {}).get("spec", {})
        retrieval_config = spec.get("retrievalConfig") or {}

        retriever_name = retrieval_config.get("retriever_name")
        retriever_namespace = retrieval_config.get("retriever_namespace", "default")
        embedding_config = retrieval_config.get("embedding_config") or {}
        embedding_model_name = embedding_config.get("model_name")
        embedding_model_namespace = embedding_config.get("model_namespace", "default")

        if not retriever_name:
            raise ValueError(
                f"Knowledge base {kb.id} has incomplete retrieval config (missing retriever_name)"
            )
        if not embedding_model_name:
            raise ValueError(
                f"Knowledge base {kb.id} has incomplete embedding config (missing model_name)"
            )

        return {
            "retriever_name": retriever_name,
            "retriever_namespace": retriever_namespace,
            "embedding_model_name": embedding_model_name,
            "embedding_model_namespace": embedding_model_namespace,
            "top_k": retrieval_config.get("top_k", 20),
            "score_threshold": retrieval_config.get("score_threshold", 0.7),
            "retrieval_mode": retrieval_config.get("retrieval_mode", "vector"),
            "hybrid_weights": retrieval_config.get("hybrid_weights") or {},
        }

    def _build_resolved_retriever_config(
        self,
        db: Session,
        user_id: int,
        name: str,
        namespace: str,
    ) -> RuntimeRetrieverConfig:
        """Resolve a Retriever Kind record into RuntimeRetrieverConfig."""
        retriever = self._get_retriever_kind(db, user_id, name, namespace)
        if retriever is None:
            raise ValueError(f"Retriever {name} (namespace: {namespace}) not found")

        spec = (retriever.json or {}).get("spec", {})
        storage_config = spec.get("storageConfig", {})

        return RuntimeRetrieverConfig(
            name=name,
            namespace=namespace,
            storage_config={
                "type": storage_config.get("type"),
                "url": storage_config.get("url"),
                "username": storage_config.get("username"),
                "password": self._decrypt_optional(storage_config.get("password")),
                "apiKey": self._decrypt_optional(storage_config.get("apiKey")),
                "indexStrategy": (
                    storage_config.get("indexStrategy")
                    if storage_config.get("indexStrategy")
                    else {"mode": "per_dataset"}
                ),
                "ext": storage_config.get("ext") or {},
            },
        )

    def _build_resolved_embedding_model_config(
        self,
        db: Session,
        user_id: int,
        model_name: str,
        model_namespace: str,
        user_name: str | None,
    ) -> RuntimeEmbeddingModelConfig:
        """Resolve a Model Kind record into RuntimeEmbeddingModelConfig."""
        model_kind = self._get_model_kind(db, user_id, model_name, model_namespace)
        if model_kind is None:
            raise ValueError(
                f"Embedding model '{model_name}' not found in namespace '{model_namespace}'"
            )

        spec = (model_kind.json or {}).get("spec", {})
        model_config = spec.get("modelConfig", {})
        env = model_config.get("env", {})
        protocol = spec.get("protocol") or env.get("model")
        custom_headers = env.get("custom_headers", {})
        if custom_headers and isinstance(custom_headers, dict):
            custom_headers = process_custom_headers_placeholders(
                custom_headers, user_name
            )

        embedding_config = spec.get("embeddingConfig", {})
        dimensions = embedding_config.get("dimensions") if embedding_config else None

        return RuntimeEmbeddingModelConfig(
            model_name=model_name,
            model_namespace=model_namespace,
            resolved_config={
                "protocol": protocol,
                "api_key": self._decrypt_optional(env.get("api_key")),
                "base_url": env.get("base_url"),
                "model_id": env.get("model_id"),
                "custom_headers": custom_headers if isinstance(custom_headers, dict) else {},
                "dimensions": dimensions,
            },
        )

    def _get_retriever_kind(
        self,
        db: Session,
        user_id: int,
        name: str,
        namespace: str,
    ) -> Kind | None:
        """Query Retriever Kind record."""
        if namespace == "default":
            return (
                db.query(Kind)
                .filter(
                    Kind.kind == "Retriever",
                    Kind.name == name,
                    Kind.namespace == namespace,
                    Kind.is_active.is_(True),
                )
                .filter((Kind.user_id == user_id) | (Kind.user_id == 0))
                .order_by(Kind.user_id.desc())
                .first()
            )
        return (
            db.query(Kind)
            .filter(
                Kind.kind == "Retriever",
                Kind.name == name,
                Kind.namespace == namespace,
                Kind.is_active.is_(True),
            )
            .first()
        )

    def _get_model_kind(
        self,
        db: Session,
        user_id: int,
        model_name: str,
        model_namespace: str,
    ) -> Kind | None:
        """Query Model Kind record."""
        if model_namespace == "default":
            return (
                db.query(Kind)
                .filter(
                    Kind.kind == "Model",
                    Kind.name == model_name,
                    Kind.namespace == model_namespace,
                    Kind.is_active.is_(True),
                )
                .filter((Kind.user_id == user_id) | (Kind.user_id == 0))
                .order_by(Kind.user_id.desc())
                .first()
            )
        return (
            db.query(Kind)
            .filter(
                Kind.kind == "Model",
                Kind.name == model_name,
                Kind.namespace == model_namespace,
                Kind.is_active.is_(True),
            )
            .first()
        )

    def _get_user_name(self, db: Session, user_id: int | None) -> str | None:
        """Query user_name from users table by user_id."""
        if user_id is None:
            return None
        user = db.query(User).filter(User.id == user_id).first()
        return user.user_name if user else None

    def _get_splitter_config(
        self, db: Session, document_id: int | None
    ) -> dict[str, Any]:
        """Get splitter_config from knowledge_documents table."""
        if document_id is None:
            return {}
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
        if doc is None:
            return {}
        return doc.splitter_config or {}

    @staticmethod
    def _decrypt_optional(value: Any) -> Any:
        """Decrypt an optional encrypted value, returning original on failure."""
        if not value:
            return value
        try:
            return decrypt_api_key(value)
        except Exception:
            return value
