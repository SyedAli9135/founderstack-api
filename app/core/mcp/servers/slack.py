"""
Slack MCP Server — Communication tools for FounderStack agents.

Provides tools for sending messages and listing channels in a connected Slack workspace.
Tools are registered with FastMCP for schema discovery / Pinecone seeding.
The MCPGateway calls the underlying async functions directly with the decrypted token.
"""

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from typing import Optional

mcp = FastMCP(
    "slack",
    instructions="Communication tools for sending Slack messages and querying workspace channels.",
)

SERVICE = "slack"


# ---------------------------------------------------------------------------
# Input Schemas
# ---------------------------------------------------------------------------

class SendMessageInput(BaseModel):
    channel: str = Field(
        ...,
        description="Slack channel ID (e.g., C01234ABCDE) or channel name (e.g., #general).",
    )
    text: str = Field(..., description="Message text. Supports Slack mrkdwn formatting.")
    thread_ts: Optional[str] = Field(
        default=None,
        description="If provided, sends the message as a reply in a thread (parent message ts).",
    )
    username: Optional[str] = Field(
        default=None,
        description="Override the bot display name for this message.",
    )


class ListChannelsInput(BaseModel):
    limit: int = Field(default=20, ge=1, le=200, description="Maximum number of channels to return (1–200).")
    exclude_archived: bool = Field(default=True, description="Exclude archived channels from the results.")
    types: str = Field(
        default="public_channel,private_channel",
        description="Comma-separated channel types: public_channel, private_channel, mpim, im.",
    )


# ---------------------------------------------------------------------------
# Core async functions
# ---------------------------------------------------------------------------

async def _send_message(params: SendMessageInput, token: str) -> dict:
    payload: dict = {"channel": params.channel, "text": params.text}
    if params.thread_ts:
        payload["thread_ts"] = params.thread_ts
    if params.username:
        payload["username"] = params.username

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    if not data.get("ok"):
        raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")

    return {
        "ok": True,
        "channel": data["channel"],
        "ts": data["ts"],
        "message_text": data.get("message", {}).get("text", params.text),
    }


async def _list_channels(params: ListChannelsInput, token: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://slack.com/api/conversations.list",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "limit": str(params.limit),
                "exclude_archived": str(params.exclude_archived).lower(),
                "types": params.types,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    if not data.get("ok"):
        raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")

    return {
        "channels": [
            {
                "id": ch["id"],
                "name": ch["name"],
                "is_private": ch.get("is_private", False),
                "is_archived": ch.get("is_archived", False),
                "num_members": ch.get("num_members", 0),
                "topic": ch.get("topic", {}).get("value", ""),
            }
            for ch in data.get("channels", [])
        ],
        "total": len(data.get("channels", [])),
    }


# ---------------------------------------------------------------------------
# FastMCP tool stubs — registered for schema/discovery only
# ---------------------------------------------------------------------------

@mcp.tool()
async def send_message(
    channel: str,
    text: str,
    thread_ts: Optional[str] = None,
    username: Optional[str] = None,
) -> dict:
    """
    Send a message to a Slack channel or thread on behalf of the connected bot.

    Supports plain text and Slack mrkdwn formatting (bold, italic, links, @mentions).
    To reply in a thread, provide the parent message's `thread_ts` timestamp.
    Returns the message timestamp (`ts`) which can be used for subsequent replies or
    reactions. Commonly used for daily briefings, agent run summaries, and alerts.
    """
    raise NotImplementedError("Use MCPGateway.execute_tool() for in-process execution.")


@mcp.tool()
async def list_channels(
    limit: int = 20,
    exclude_archived: bool = True,
    types: str = "public_channel,private_channel",
) -> dict:
    """
    List channels in the connected Slack workspace.

    Returns each channel's ID, name, topic, member count, and privacy/archive status.
    Use the returned channel IDs with `send_message` to target specific channels.
    Supports filtering by channel type (public, private, DMs, group DMs).
    """
    raise NotImplementedError("Use MCPGateway.execute_tool() for in-process execution.")


# ---------------------------------------------------------------------------
# Tool dispatch table
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {
    "send_message": lambda params, token, _db: _send_message(SendMessageInput(**params), token),
    "list_channels": lambda params, token, _db: _list_channels(ListChannelsInput(**params), token),
}
