"""
Tool Manifest Seed Script — Workflow 5

Reads all FastMCP registered tools across all servers via the MCPGateway,
embeds their docstrings and input schemas via Cohere, and upserts the vectors
into the Pinecone 'founderstack-tools' index for semantic tool discovery by agents.

Usage:
    uv run python -m app.core.mcp.registry.seed

Required env vars:
    COHERE_API_KEY
    PINECONE_API_KEY
    PINECONE_INDEX_TOOLS  (default: "founderstack-tools")
"""

import asyncio
import json
import sys
import time
from typing import Any

import cohere
from pinecone import Pinecone

from app.config import settings
from app.core.mcp.gateway import mcp_gateway


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

EMBED_MODEL = "embed-english-v3.0"
EMBED_INPUT_TYPE = "search_document"
PINECONE_NAMESPACE = "tools"
BATCH_SIZE = 96  # Cohere embed-v3 max is 96 texts per call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_tool_text(service: str, tool_name: str, description: str, input_schema: dict) -> str:
    """Compose a rich text string to embed for each tool."""
    schema_str = json.dumps(input_schema, indent=2)
    return (
        f"Service: {service}\n"
        f"Tool: {service}.{tool_name}\n"
        f"Description: {description.strip()}\n"
        f"Parameters:\n{schema_str}"
    )


def _build_vector_id(service: str, tool_name: str) -> str:
    return f"{service}__{tool_name}"


def _build_metadata(service: str, tool: dict) -> dict:
    return {
        "service": service,
        "tool_name": tool["tool_name"],
        "qualified_name": tool["qualified_name"],
        "description": tool["description"],
        "input_schema": json.dumps(tool["input_schema"]),
    }


# ---------------------------------------------------------------------------
# Main seed function
# ---------------------------------------------------------------------------

async def seed_tools() -> None:
    print("=" * 60)
    print("FounderStack — Tool Manifest Seed Script")
    print("=" * 60)

    # 1. Collect all tool manifests from the gateway
    print("\n[1/4] Collecting tool manifests from MCP servers...")
    all_tools = await mcp_gateway.list_all_tools()
    print(f"      Found {len(all_tools)} tools across {len(mcp_gateway.available_services)} services.")
    for tool in all_tools:
        print(f"      ✓ {tool['qualified_name']}")

    if not all_tools:
        print("\nNo tools found. Exiting.")
        sys.exit(1)

    # 2. Build text representations for embedding
    print("\n[2/4] Building text representations for embedding...")
    texts = [
        _build_tool_text(
            service=tool["service"],
            tool_name=tool["tool_name"],
            description=tool["description"],
            input_schema=tool["input_schema"],
        )
        for tool in all_tools
    ]

    # 3. Embed via Cohere
    print(f"\n[3/4] Embedding {len(texts)} tool manifests via Cohere ({EMBED_MODEL})...")
    cohere_api_key = settings.COHERE_API_KEY.get_secret_value()
    if not cohere_api_key:
        print("ERROR: COHERE_API_KEY is not set in .env")
        sys.exit(1)

    co = cohere.Client(cohere_api_key)

    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        print(f"      Embedding batch {i // BATCH_SIZE + 1} ({len(batch)} texts)...")
        response = co.embed(
            texts=batch,
            model=EMBED_MODEL,
            input_type=EMBED_INPUT_TYPE,
        )
        all_embeddings.extend(response.embeddings)
        if i + BATCH_SIZE < len(texts):
            time.sleep(0.5)

    print(f"      ✓ Got {len(all_embeddings)} embeddings (dim={len(all_embeddings[0])}).")

    # 4. Upsert into Pinecone
    print(f"\n[4/4] Upserting into Pinecone index '{settings.PINECONE_INDEX_TOOLS}'...")
    pinecone_api_key = settings.PINECONE_API_KEY.get_secret_value()
    if not pinecone_api_key:
        print("ERROR: PINECONE_API_KEY is not set in .env")
        sys.exit(1)

    pc = Pinecone(api_key=pinecone_api_key)
    index = pc.Index(settings.PINECONE_INDEX_TOOLS)

    vectors: list[dict[str, Any]] = []
    for tool, embedding in zip(all_tools, all_embeddings):
        vectors.append({
            "id": _build_vector_id(tool["service"], tool["tool_name"]),
            "values": embedding,
            "metadata": _build_metadata(tool["service"], tool),
        })

    # Upsert in batches of 100
    for i in range(0, len(vectors), 100):
        batch = vectors[i : i + 100]
        index.upsert(vectors=batch, namespace=PINECONE_NAMESPACE)
        print(f"      Upserted {len(batch)} vectors (batch {i // 100 + 1}).")

    print(f"\n{'=' * 60}")
    print(f"✅ Done! {len(vectors)} tool vectors upserted to '{settings.PINECONE_INDEX_TOOLS}'")
    print(f"   Namespace : '{PINECONE_NAMESPACE}'")
    print(f"   Services  : {', '.join(mcp_gateway.available_services)}")
    print(f"   Tools     : {', '.join(t['qualified_name'] for t in all_tools)}")
    print(f"{'=' * 60}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(seed_tools())
