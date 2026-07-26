"""
LinkedIn MCP Server — Marketing tools for FounderStack agents.

Provides tools to draft and publish LinkedIn posts on behalf of a connected member.
FastMCP stubs handle schema/discovery; the MCPGateway calls the underlying
async functions directly with the decrypted access token.
"""

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from typing import Optional

mcp = FastMCP(
    "linkedin",
    instructions="Marketing tools for drafting and publishing LinkedIn posts.",
)

SERVICE = "linkedin"
LI_API = "https://api.linkedin.com/v2"


# ---------------------------------------------------------------------------
# Input Schemas
# ---------------------------------------------------------------------------

class DraftPostInput(BaseModel):
    text: str = Field(
        ...,
        description="Post text content (up to 3000 characters). Supports hashtags and @mentions.",
    )
    visibility: str = Field(
        default="PUBLIC",
        description="Post visibility: 'PUBLIC' (anyone) or 'CONNECTIONS' (1st-degree only).",
    )
    article_url: Optional[str] = Field(
        default=None,
        description="Optional URL to attach as a linked article. LinkedIn generates a preview.",
    )
    article_title: Optional[str] = Field(
        default=None,
        description="Title for the linked article (only used if article_url is set).",
    )
    article_description: Optional[str] = Field(
        default=None,
        description="Description for the linked article (only used if article_url is set).",
    )


# ---------------------------------------------------------------------------
# Core async function
# ---------------------------------------------------------------------------

async def _draft_post(params: DraftPostInput, token: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    async with httpx.AsyncClient() as client:
        # Fetch the member's person URN
        profile_resp = await client.get(f"{LI_API}/userinfo", headers=headers)
        profile_resp.raise_for_status()
        profile = profile_resp.json()
        person_urn = f"urn:li:person:{profile['sub']}"

        # Build UGC post payload
        if params.article_url:
            share_content: dict = {
                "shareCommentary": {"text": params.text},
                "shareMediaCategory": "ARTICLE",
                "media": [
                    {
                        "status": "READY",
                        "originalUrl": params.article_url,
                        "title": {"text": params.article_title or ""},
                        "description": {"text": params.article_description or ""},
                    }
                ],
            }
        else:
            share_content = {
                "shareCommentary": {"text": params.text},
                "shareMediaCategory": "NONE",
            }

        post_payload = {
            "author": person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {"com.linkedin.ugc.ShareContent": share_content},
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": params.visibility},
        }

        post_resp = await client.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers=headers,
            json=post_payload,
        )
        post_resp.raise_for_status()

    post_id = post_resp.headers.get("x-restli-id", "")
    return {
        "post_id": post_id,
        "post_urn": f"urn:li:ugcPost:{post_id}",
        "author_urn": person_urn,
        "visibility": params.visibility,
        "text_preview": params.text[:100] + ("..." if len(params.text) > 100 else ""),
        "has_article": bool(params.article_url),
    }


# ---------------------------------------------------------------------------
# FastMCP tool stubs — registered for schema/discovery only
# ---------------------------------------------------------------------------

@mcp.tool()
async def draft_post(
    text: str,
    visibility: str = "PUBLIC",
    article_url: Optional[str] = None,
    article_title: Optional[str] = None,
    article_description: Optional[str] = None,
) -> dict:
    """
    Publish a text post (with optional article link) to LinkedIn on behalf of the connected member.

    First fetches the authenticated member's LinkedIn URN, then submits the post via the
    UGC Posts API. Supports PUBLIC or CONNECTIONS visibility. If an article_url is provided,
    the post includes a link share with a generated preview card. Returns the post ID and
    author URN. Ideal for sharing agent-generated content, thought leadership, or updates.
    """
    raise NotImplementedError("Use MCPGateway.execute_tool() for in-process execution.")


# ---------------------------------------------------------------------------
# Tool dispatch table
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {
    "draft_post": lambda params, token, _db: _draft_post(DraftPostInput(**params), token),
}
