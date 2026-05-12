# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Artifact uploader service for uploading .duckdb files to Backend.

Handles uploading generated .duckdb files to the Backend's internal
artifact upload endpoint, reusing the existing StorageBackend.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from knowledge_runtime.config import get_settings

logger = logging.getLogger(__name__)


class ArtifactUploader:
    """Uploads .duckdb files to Backend internal artifact endpoint."""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def upload_duckdb_artifact(
        self,
        attachment_id: int,
        duckdb_binary_data: bytes,
        auth_token: Optional[str] = None,
    ) -> Optional[int]:
        """Upload a .duckdb file to the Backend internal upload endpoint.

        Args:
            attachment_id: The original attachment ID.
            duckdb_binary_data: Binary content of the .duckdb file.
            auth_token: Optional auth token for Backend internal endpoint.

        Returns:
            The new attachment ID for the .duckdb file, or None on failure.
        """
        backend_url = self._settings.backend_internal_url
        internal_token = self._settings.internal_service_token
        token = auth_token or internal_token

        upload_url = f"{backend_url}/api/internal/data/artifacts/upload"

        try:
            headers = {}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            files = {
                "file": (f"duckdb_{attachment_id}.duckdb", duckdb_binary_data, "application/octet-stream"),
            }
            data = {
                "attachment_id": str(attachment_id),
                "original_filename": f"duckdb_{attachment_id}.duckdb",
                "file_extension": ".duckdb",
            }

            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    upload_url,
                    headers=headers,
                    files=files,
                    data=data,
                )
                response.raise_for_status()

                result = response.json()
                duckdb_attachment_id = result.get("attachment_id")

                logger.info(
                    "Uploaded .duckdb artifact for attachment %d, new ID: %s",
                    attachment_id,
                    duckdb_attachment_id,
                )
                return duckdb_attachment_id

        except httpx.HTTPStatusError as e:
            logger.error(
                "Failed to upload .duckdb artifact for attachment %d: HTTP %d - %s",
                attachment_id,
                e.response.status_code,
                e.response.text[:200],
            )
            return None
        except Exception as e:
            logger.error(
                "Failed to upload .duckdb artifact for attachment %d: %s",
                attachment_id,
                e,
            )
            return None


# Module-level singleton
_artifact_uploader: Optional[ArtifactUploader] = None


def get_artifact_uploader() -> ArtifactUploader:
    """Get the global ArtifactUploader instance."""
    global _artifact_uploader
    if _artifact_uploader is None:
        _artifact_uploader = ArtifactUploader()
    return _artifact_uploader
