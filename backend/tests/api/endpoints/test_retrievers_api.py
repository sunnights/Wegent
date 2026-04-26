# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import AsyncMock, patch

from app.services.rag.runtime_specs import ConnectionTestRuntimeSpec


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_retriever_test_connection_uses_local_gateway(
    test_client,
    test_token: str,
):
    """Test that test-connection always uses LocalRagGateway (no remote fallback)."""
    mock_result = {
        "success": True,
        "message": "Connection successful",
    }

    with patch(
        "app.api.endpoints.adapter.retrievers.LocalRagGateway",
    ) as mock_gateway_cls:
        mock_instance = AsyncMock()
        mock_instance.test_connection.return_value = mock_result
        mock_gateway_cls.return_value = mock_instance

        response = test_client.post(
            "/api/retrievers/test-connection",
            headers=_auth_header(test_token),
            json={
                "storage_type": "qdrant",
                "url": "http://qdrant:6333",
                "username": "alice",
                "password": "secret",
                "api_key": "api-token",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "Connection successful",
    }
    mock_gateway_cls.assert_called_once()
    mock_instance.test_connection.assert_awaited_once()

    runtime_spec = mock_instance.test_connection.await_args.args[0]
    assert isinstance(runtime_spec, ConnectionTestRuntimeSpec)
    assert runtime_spec.retriever_config.storage_config == {
        "type": "qdrant",
        "url": "http://qdrant:6333",
        "username": "alice",
        "password": "secret",
        "apiKey": "api-token",
        "indexStrategy": {"mode": "per_dataset"},
        "ext": {},
    }


def test_retriever_test_connection_validates_required_fields(
    test_client,
    test_token: str,
):
    response = test_client.post(
        "/api/retrievers/test-connection",
        headers=_auth_header(test_token),
        json={"storage_type": "qdrant"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "message": "Missing required fields: storage_type, url",
    }
