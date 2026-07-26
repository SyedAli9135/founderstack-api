"""
Unit tests for the Workflow 5 tool-manifest seed script
(app/core/mcp/registry/seed.py).

Only the pure helper functions are exercised here — the real `seed_tools()`
entry point calls out to Cohere and Pinecone, which is an integration-level
concern (see the manual test instructions instead of a unit test for that path).
"""

from app.core.mcp.registry.seed import (
    _build_metadata,
    _build_tool_text,
    _build_vector_id,
)


def test_build_vector_id_joins_service_and_tool_with_double_underscore():
    assert _build_vector_id("stripe", "create_invoice") == "stripe__create_invoice"


def test_build_tool_text_embeds_service_tool_description_and_schema():
    text = _build_tool_text(
        service="slack",
        tool_name="send_message",
        description="  Send a Slack message.  ",
        input_schema={"type": "object", "properties": {"channel": {"type": "string"}}},
    )

    assert "Service: slack" in text
    assert "Tool: slack.send_message" in text
    # Leading/trailing whitespace on the docstring is stripped
    assert "Description: Send a Slack message." in text
    assert '"channel"' in text


def test_build_metadata_matches_pinecone_metadata_shape():
    tool = {
        "tool_name": "get_mrr",
        "qualified_name": "stripe.get_mrr",
        "description": "Calculate MRR.",
        "input_schema": {"type": "object", "properties": {}},
    }

    metadata = _build_metadata("stripe", tool)

    assert metadata["service"] == "stripe"
    assert metadata["tool_name"] == "get_mrr"
    assert metadata["qualified_name"] == "stripe.get_mrr"
    assert metadata["description"] == "Calculate MRR."
    # input_schema must be JSON-encoded (Pinecone metadata values can't be nested dicts)
    assert isinstance(metadata["input_schema"], str)
    assert '"properties"' in metadata["input_schema"]
