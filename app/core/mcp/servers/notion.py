"""
Notion MCP Server — Knowledge-base tools for FounderStack agents.

Provides tools to read from and write to Notion pages.
FastMCP stubs handle schema/discovery; the MCPGateway calls the underlying
async functions directly with the decrypted access token.
"""

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from typing import Optional, List

mcp = FastMCP(
    "notion",
    instructions="Knowledge tools for reading and writing Notion pages and databases.",
)

SERVICE = "notion"
NOTION_VERSION = "2022-06-28"


# ---------------------------------------------------------------------------
# Input Schemas
# ---------------------------------------------------------------------------

class ReadPageInput(BaseModel):
    page_id: str = Field(
        ...,
        description="Notion page ID (UUID from page URL). Hyphens are optional.",
    )
    include_children: bool = Field(
        default=True,
        description="If true, also fetches the page's child blocks (the page content).",
    )


class WritePageInput(BaseModel):
    parent_page_id: str = Field(
        ...,
        description="ID of the parent Notion page under which the new page will be created.",
    )
    title: str = Field(..., description="Title of the new Notion page.")
    content_markdown: str = Field(
        ...,
        description=(
            "Content as plain text / simplified markdown. Lines starting with "
            "'# ', '## ', '### ' become headings. Lines starting with '- ' "
            "become bullets. All other non-empty lines become paragraphs."
        ),
    )
    icon_emoji: Optional[str] = Field(default=None, description="Optional emoji page icon (e.g. '📄').")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _notion_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _plain_text(rich_text_list: List[dict]) -> str:
    return "".join(rt.get("plain_text", "") for rt in rich_text_list)


def _markdown_to_blocks(markdown: str) -> List[dict]:
    """Convert simplified markdown to Notion block objects."""
    blocks: List[dict] = []
    for line in markdown.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("### "):
            blocks.append({"object": "block", "type": "heading_3",
                            "heading_3": {"rich_text": [{"type": "text", "text": {"content": s[4:]}}]}})
        elif s.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2",
                            "heading_2": {"rich_text": [{"type": "text", "text": {"content": s[3:]}}]}})
        elif s.startswith("# "):
            blocks.append({"object": "block", "type": "heading_1",
                            "heading_1": {"rich_text": [{"type": "text", "text": {"content": s[2:]}}]}})
        elif s.startswith("- "):
            blocks.append({"object": "block", "type": "bulleted_list_item",
                            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": s[2:]}}]}})
        else:
            blocks.append({"object": "block", "type": "paragraph",
                            "paragraph": {"rich_text": [{"type": "text", "text": {"content": s}}]}})
    return blocks


# ---------------------------------------------------------------------------
# Core async functions
# ---------------------------------------------------------------------------

async def _read_page(params: ReadPageInput, token: str) -> dict:
    headers = _notion_headers(token)
    page_id = params.page_id.replace("-", "")

    async with httpx.AsyncClient() as client:
        page_resp = await client.get(f"https://api.notion.com/v1/pages/{page_id}", headers=headers)
        page_resp.raise_for_status()
        page = page_resp.json()

        title_prop = page.get("properties", {}).get("title", {})
        title = _plain_text(title_prop.get("title", []))

        result: dict = {
            "page_id": page["id"],
            "title": title,
            "created_time": page.get("created_time"),
            "last_edited_time": page.get("last_edited_time"),
            "url": page.get("url"),
        }

        if params.include_children:
            blocks_resp = await client.get(
                f"https://api.notion.com/v1/blocks/{page_id}/children",
                headers=headers,
                params={"page_size": "100"},
            )
            blocks_resp.raise_for_status()
            blocks_data = blocks_resp.json()
            lines: List[str] = []
            for block in blocks_data.get("results", []):
                btype = block.get("type", "")
                rich_text = block.get(btype, {}).get("rich_text", [])
                text = _plain_text(rich_text)
                if text:
                    lines.append(text)
            result["content"] = "\n".join(lines)
            result["block_count"] = len(blocks_data.get("results", []))

    return result


async def _write_page(params: WritePageInput, token: str) -> dict:
    headers = _notion_headers(token)
    parent_id = params.parent_page_id.replace("-", "")
    blocks = _markdown_to_blocks(params.content_markdown)

    payload: dict = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "properties": {"title": {"title": [{"type": "text", "text": {"content": params.title}}]}},
        "children": blocks,
    }
    if params.icon_emoji:
        payload["icon"] = {"type": "emoji", "emoji": params.icon_emoji}

    async with httpx.AsyncClient() as client:
        resp = await client.post("https://api.notion.com/v1/pages", headers=headers, json=payload)
        resp.raise_for_status()
        page = resp.json()

    return {
        "page_id": page["id"],
        "url": page.get("url"),
        "title": params.title,
        "blocks_written": len(blocks),
        "created_time": page.get("created_time"),
    }


# ---------------------------------------------------------------------------
# FastMCP tool stubs — registered for schema/discovery only
# ---------------------------------------------------------------------------

@mcp.tool()
async def read_page(page_id: str, include_children: bool = True) -> dict:
    """
    Read a Notion page's properties and content blocks.

    Retrieves the page title, creation/edit timestamps, URL, and optionally all
    child content blocks rendered as plain text. Use this to fetch SOPs, reference
    documents, or knowledge-base entries before drafting agent responses or summaries.
    """
    raise NotImplementedError("Use MCPGateway.execute_tool() for in-process execution.")


@mcp.tool()
async def write_page(
    parent_page_id: str,
    title: str,
    content_markdown: str,
    icon_emoji: Optional[str] = None,
) -> dict:
    """
    Create a new Notion page under a parent page with formatted content.

    Converts simplified markdown (headings #/##/###, bullet lists -, paragraphs)
    into native Notion blocks. Returns the new page URL and ID.
    Ideal for drafting SOPs, agent run summaries, blog posts, or structured documents.
    """
    raise NotImplementedError("Use MCPGateway.execute_tool() for in-process execution.")


# ---------------------------------------------------------------------------
# Tool dispatch table
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {
    "read_page": lambda params, token, _db: _read_page(ReadPageInput(**params), token),
    "write_page": lambda params, token, _db: _write_page(WritePageInput(**params), token),
}
