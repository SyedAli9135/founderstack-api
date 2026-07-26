"""
MCPGateway — routes tool execution calls to the correct FastMCP server instance.

Architecture:
- FastMCP `mcp` instances on each server handle schema registration and tool discovery.
- `TOOL_HANDLERS` dicts on each server module map tool names to async callables
  that accept (params, token, db) and do the actual API work.
- The gateway looks up the right handler, fetches the integration token from the
  token_store, and calls the handler — keeping org context fully out of the schema.

Usage:
    from app.core.mcp.gateway import mcp_gateway

    result = await mcp_gateway.execute_tool(
        tool_name="stripe.create_invoice",
        params={"customer_id": "cus_xxx", "amount_cents": 5000},
        org_id="org_123",
        db=db_session,
    )

Tool name format: "{service}.{tool_function_name}"
"""

from typing import Any
from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP

from app.core.mcp.servers import stripe as stripe_server
from app.core.mcp.servers import slack as slack_server
from app.core.mcp.servers import notion as notion_server
from app.core.mcp.servers import github as github_server
from app.core.mcp.servers import linkedin as linkedin_server
from app.core.integrations.token_store import get_integration_token


class MCPGateway:
    """
    Central dispatcher for all in-process MCP tool calls.

    Maintains a registry of FastMCP server instances (for tool discovery/schema)
    and TOOL_HANDLERS tables (for execution). Resolves "{service}.{tool}" identifiers,
    fetches the decrypted integration token, and calls the appropriate handler.
    """

    def __init__(self) -> None:
        # FastMCP server instances — used for list_tools() / schema discovery
        self._servers: dict[str, FastMCP] = {
            "stripe": stripe_server.mcp,
            "slack": slack_server.mcp,
            "notion": notion_server.mcp,
            "github": github_server.mcp,
            "linkedin": linkedin_server.mcp,
        }

        # Execution handlers — map tool name → async callable(params, token, db)
        self._handlers: dict[str, dict[str, Any]] = {
            "stripe": stripe_server.TOOL_HANDLERS,
            "slack": slack_server.TOOL_HANDLERS,
            "notion": notion_server.TOOL_HANDLERS,
            "github": github_server.TOOL_HANDLERS,
            "linkedin": linkedin_server.TOOL_HANDLERS,
        }

    @property
    def available_services(self) -> list[str]:
        """Return a list of registered service names."""
        return list(self._servers.keys())

    async def list_all_tools(self) -> list[dict]:
        """
        Return a flattened list of all registered tools across all servers.

        Each entry: { service, tool_name, qualified_name, description, input_schema }.
        Used by the seed script to embed tool manifests into Pinecone.
        """
        all_tools: list[dict] = []
        for service, server in self._servers.items():
            tools = await server.list_tools()
            for tool in tools:
                all_tools.append({
                    "service": service,
                    "tool_name": tool.name,
                    "qualified_name": f"{service}.{tool.name}",
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema,
                })
        return all_tools

    async def execute_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        org_id: str,
        db: Any,
    ) -> Any:
        """
        Execute a tool by its qualified name ("{service}.{tool}").

        1. Parses the dot-notation tool name.
        2. Retrieves the integration token from the token store.
        3. Calls the corresponding TOOL_HANDLER with (params, token, db).

        Args:
            tool_name: Dot-separated identifier, e.g. "stripe.create_invoice".
            params:    Tool input parameters as a dict matching the tool's Pydantic schema.
            org_id:    Organization ID used to retrieve the integration token.
            db:        AsyncSession for DB access (token decryption).

        Returns:
            The raw return value from the tool handler.

        Raises:
            HTTPException 400: if tool_name format is invalid.
            HTTPException 404: if the service or tool is not found.
            HTTPException 401: if the integration token is missing/expired.
        """
        # Parse "service.tool_fn" format
        parts = tool_name.split(".", 1)
        if len(parts) != 2:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tool name '{tool_name}'. Expected format: 'service.tool_name'.",
            )

        service, fn_name = parts

        # Validate service exists
        if service not in self._servers:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No MCP server registered for service '{service}'. "
                    f"Available: {', '.join(self.available_services)}"
                ),
            )

        # Validate tool exists (checks schema registry)
        available_tools = await self._servers[service].list_tools()
        tool_names = [t.name for t in available_tools]
        if fn_name not in tool_names:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Tool '{fn_name}' not found on '{service}' server. "
                    f"Available tools: {', '.join(tool_names)}"
                ),
            )

        # Get the execution handler
        handler = self._handlers[service].get(fn_name)
        if handler is None:
            raise HTTPException(
                status_code=501,
                detail=f"Tool '{tool_name}' has no execution handler registered.",
            )

        # Fetch the decrypted integration token
        # ToolAuthExpiredError (HTTP 401) is raised automatically if not connected
        token = await get_integration_token(db, org_id, service)

        # Execute the tool handler: (params_dict, token, db) → result
        return await handler(params, token, db)


# Singleton gateway instance — import this throughout the app
mcp_gateway = MCPGateway()
