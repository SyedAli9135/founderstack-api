"""
Unit tests for MCPGateway (app/core/mcp/gateway.py) — Workflow 5.

Covers tool-name parsing/validation, service/tool discovery, token retrieval,
and dispatch to the correct TOOL_HANDLERS entry. httpx network calls made by
the underlying handler are faked; `get_integration_token` is mocked directly
since its own DB/decryption behavior belongs to Workflow 4's test coverage.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.core.mcp.gateway import mcp_gateway
from app.core.exceptions import ToolAuthExpiredError
from app.core.mcp.servers import stripe as stripe_server
from tests.mcp_test_utils import FakeResponse, patch_httpx_client


def test_available_services_lists_all_registered_servers():
    assert set(mcp_gateway.available_services) == {"stripe", "slack", "notion", "github", "linkedin"}


@pytest.mark.asyncio
async def test_list_all_tools_returns_qualified_names_for_every_service():
    tools = await mcp_gateway.list_all_tools()
    qualified_names = {t["qualified_name"] for t in tools}

    assert "stripe.create_invoice" in qualified_names
    assert "slack.send_message" in qualified_names
    assert "notion.read_page" in qualified_names
    assert "github.review_pr" in qualified_names
    assert "linkedin.draft_post" in qualified_names
    # Every tool manifest carries the fields the seed script depends on
    for tool in tools:
        assert tool["service"] in mcp_gateway.available_services
        assert tool["description"], f"{tool['qualified_name']} is missing a docstring/description"
        assert "properties" in tool["input_schema"] or tool["input_schema"] == {}


@pytest.mark.asyncio
async def test_execute_tool_rejects_malformed_tool_name():
    with pytest.raises(HTTPException) as excinfo:
        await mcp_gateway.execute_tool("not_qualified", {}, "org_1", db=None)

    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_execute_tool_rejects_unknown_service():
    with pytest.raises(HTTPException) as excinfo:
        await mcp_gateway.execute_tool("nonexistent.do_thing", {}, "org_1", db=None)

    assert excinfo.value.status_code == 404
    assert "nonexistent" in excinfo.value.detail


@pytest.mark.asyncio
async def test_execute_tool_rejects_unknown_tool_on_known_service():
    with pytest.raises(HTTPException) as excinfo:
        await mcp_gateway.execute_tool("stripe.delete_everything", {}, "org_1", db=None)

    assert excinfo.value.status_code == 404
    assert "delete_everything" in excinfo.value.detail


@pytest.mark.asyncio
async def test_execute_tool_raises_401_when_integration_not_connected():
    with patch(
        "app.core.mcp.gateway.get_integration_token",
        new=AsyncMock(side_effect=ToolAuthExpiredError("stripe")),
    ):
        with pytest.raises(ToolAuthExpiredError) as excinfo:
            await mcp_gateway.execute_tool("stripe.get_mrr", {}, "org_1", db=None)

    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_execute_tool_dispatches_to_handler_with_decrypted_token():
    fake_token = "sk_test_from_vault"
    responses = [FakeResponse({
        "data": [],
        "has_more": False,
    })]
    patcher, fake_client = patch_httpx_client(stripe_server, responses)

    with patch(
        "app.core.mcp.gateway.get_integration_token",
        new=AsyncMock(return_value=fake_token),
    ) as mock_get_token, patcher:
        result = await mcp_gateway.execute_tool(
            "stripe.list_customers", {"limit": 3}, "org_42", db="fake_db_session"
        )

    mock_get_token.assert_awaited_once_with("fake_db_session", "org_42", "stripe")
    assert result["customers"] == []
    assert fake_client.requests[0][2]["headers"]["Authorization"] == f"Bearer {fake_token}"
