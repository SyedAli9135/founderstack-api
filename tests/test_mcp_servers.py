"""
Unit tests for the Workflow 5 MCP integration servers
(app/core/mcp/servers/{stripe,slack,notion,github,linkedin}.py).

Each server's core `_*` functions make outbound httpx calls — those are faked via
`tests/mcp_test_utils.py` so no network access or real credentials are required.
Each TOOL_HANDLERS entry is also exercised to confirm the dict-of-params -> Pydantic
model -> handler wiring the MCPGateway relies on actually works end to end.
"""

import pytest

from app.core.mcp.servers import stripe as stripe_server
from app.core.mcp.servers import slack as slack_server
from app.core.mcp.servers import notion as notion_server
from app.core.mcp.servers import github as github_server
from app.core.mcp.servers import linkedin as linkedin_server

from tests.mcp_test_utils import FakeResponse, patch_httpx_client


# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stripe_create_invoice_success():
    responses = [
        FakeResponse({"id": "ii_123"}),  # invoiceitems
        FakeResponse({
            "id": "in_123",
            "status": "open",
            "amount_due": 5000,
            "currency": "usd",
            "hosted_invoice_url": "https://invoice.stripe.com/in_123",
        }),
    ]
    patcher, fake = patch_httpx_client(stripe_server, responses)
    with patcher:
        result = await stripe_server.TOOL_HANDLERS["create_invoice"](
            {"customer_id": "cus_abc", "amount_cents": 5000}, "sk_test_123", None
        )

    assert result["invoice_id"] == "in_123"
    assert result["amount_due"] == 5000
    assert result["hosted_invoice_url"] == "https://invoice.stripe.com/in_123"
    assert fake.requests[0][0] == "POST"
    assert "invoiceitems" in fake.requests[0][1]
    assert fake.requests[1][2]["headers"]["Authorization"] == "Bearer sk_test_123"


@pytest.mark.asyncio
async def test_stripe_list_customers_filters_by_email():
    responses = [FakeResponse({
        "data": [{"id": "cus_1", "email": "a@b.com", "name": "A", "created": 1, "delinquent": False}],
        "has_more": False,
    })]
    patcher, fake = patch_httpx_client(stripe_server, responses)
    with patcher:
        result = await stripe_server.TOOL_HANDLERS["list_customers"](
            {"limit": 5, "email": "a@b.com"}, "sk_test_123", None
        )

    assert result["customers"][0]["id"] == "cus_1"
    assert fake.requests[0][2]["params"]["email"] == "a@b.com"
    assert fake.requests[0][2]["params"]["limit"] == "5"


@pytest.mark.asyncio
async def test_stripe_refund_payment_full_refund():
    responses = [FakeResponse({"id": "re_1", "amount": 5000, "currency": "usd", "status": "succeeded"})]
    patcher, fake = patch_httpx_client(stripe_server, responses)
    with patcher:
        result = await stripe_server.TOOL_HANDLERS["refund_payment"](
            {"payment_intent_id": "pi_1"}, "sk_test_123", None
        )

    assert result["status"] == "succeeded"
    # No amount/reason provided -> not sent in the refund payload
    assert "amount" not in fake.requests[0][2]["data"]
    assert "reason" not in fake.requests[0][2]["data"]


@pytest.mark.asyncio
async def test_stripe_get_mrr_normalizes_yearly_and_monthly_intervals():
    responses = [FakeResponse({
        "data": [
            {
                "items": {"data": [{
                    "price": {"unit_amount": 12000, "recurring": {"interval": "year", "interval_count": 1}},
                    "quantity": 1,
                }]},
            },
            {
                "items": {"data": [{
                    "price": {"unit_amount": 5000, "recurring": {"interval": "month", "interval_count": 1}},
                    "quantity": 2,
                }]},
            },
        ],
        "has_more": False,
    })]
    patcher, fake = patch_httpx_client(stripe_server, responses)
    with patcher:
        result = await stripe_server.TOOL_HANDLERS["get_mrr"]({}, "sk_test_123", None)

    # 12000/12 = 1000 (yearly sub) + 5000*2 = 10000 (monthly sub) = 11000 cents
    assert result["mrr_cents"] == 11000
    assert result["mrr_usd"] == 110.0
    assert result["active_subscriptions"] == 2


@pytest.mark.asyncio
async def test_stripe_api_error_propagates():
    """A non-2xx Stripe response should raise, not silently succeed."""
    import httpx as httpx_module

    patcher, _fake = patch_httpx_client(stripe_server, [FakeResponse({"error": "bad key"}, status_code=401)])
    with patcher, pytest.raises(httpx_module.HTTPStatusError):
        await stripe_server.TOOL_HANDLERS["list_customers"]({}, "bad_key", None)


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_slack_send_message_success():
    responses = [FakeResponse({"ok": True, "channel": "C123", "ts": "111.222", "message": {"text": "hi"}})]
    patcher, fake = patch_httpx_client(slack_server, responses)
    with patcher:
        result = await slack_server.TOOL_HANDLERS["send_message"](
            {"channel": "#general", "text": "hi"}, "xoxb-token", None
        )

    assert result["ok"] is True
    assert result["ts"] == "111.222"
    assert fake.requests[0][2]["json"]["channel"] == "#general"


@pytest.mark.asyncio
async def test_slack_send_message_raises_on_slack_error_payload():
    """Slack returns HTTP 200 with ok=false on API errors — must still raise."""
    responses = [FakeResponse({"ok": False, "error": "channel_not_found"})]
    patcher, _fake = patch_httpx_client(slack_server, responses)
    with patcher, pytest.raises(RuntimeError, match="channel_not_found"):
        await slack_server.TOOL_HANDLERS["send_message"]({"channel": "#nope", "text": "hi"}, "xoxb-token", None)


@pytest.mark.asyncio
async def test_slack_list_channels_success():
    responses = [FakeResponse({
        "ok": True,
        "channels": [{"id": "C1", "name": "general", "is_private": False, "is_archived": False,
                      "num_members": 3, "topic": {"value": "chat"}}],
    })]
    patcher, fake = patch_httpx_client(slack_server, responses)
    with patcher:
        result = await slack_server.TOOL_HANDLERS["list_channels"]({}, "xoxb-token", None)

    assert result["total"] == 1
    assert result["channels"][0]["name"] == "general"
    assert fake.requests[0][2]["params"]["exclude_archived"] == "true"


# ---------------------------------------------------------------------------
# Notion
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notion_read_page_includes_children_content():
    responses = [
        FakeResponse({
            "id": "page_1",
            "properties": {"title": {"title": [{"plain_text": "My Doc"}]}},
            "created_time": "2026-01-01T00:00:00Z",
            "last_edited_time": "2026-01-02T00:00:00Z",
            "url": "https://notion.so/page_1",
        }),
        FakeResponse({
            "results": [
                {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Hello world"}]}},
            ],
        }),
    ]
    patcher, fake = patch_httpx_client(notion_server, responses)
    with patcher:
        result = await notion_server.TOOL_HANDLERS["read_page"]({"page_id": "page-1"}, "secret_token", None)

    assert result["title"] == "My Doc"
    assert result["content"] == "Hello world"
    assert result["block_count"] == 1
    # Hyphens are stripped from the page_id before hitting the Notion API
    assert fake.requests[0][1].endswith("/pages/page1")


@pytest.mark.asyncio
async def test_notion_read_page_skips_children_when_not_requested():
    responses = [FakeResponse({
        "id": "page_1",
        "properties": {"title": {"title": [{"plain_text": "My Doc"}]}},
        "url": "https://notion.so/page_1",
    })]
    patcher, fake = patch_httpx_client(notion_server, responses)
    with patcher:
        result = await notion_server.TOOL_HANDLERS["read_page"](
            {"page_id": "page_1", "include_children": False}, "secret_token", None
        )

    assert "content" not in result
    assert len(fake.requests) == 1  # only the page fetch, no block-children call


def test_notion_markdown_to_blocks_converts_headings_and_bullets():
    blocks = notion_server._markdown_to_blocks("# Title\n## Sub\n- item one\nplain text")

    assert blocks[0]["type"] == "heading_1"
    assert blocks[1]["type"] == "heading_2"
    assert blocks[2]["type"] == "bulleted_list_item"
    assert blocks[3]["type"] == "paragraph"


@pytest.mark.asyncio
async def test_notion_write_page_success():
    responses = [FakeResponse({
        "id": "new_page_1",
        "url": "https://notion.so/new_page_1",
        "created_time": "2026-01-01T00:00:00Z",
    })]
    patcher, fake = patch_httpx_client(notion_server, responses)
    with patcher:
        result = await notion_server.TOOL_HANDLERS["write_page"](
            {"parent_page_id": "parent_1", "title": "New SOP", "content_markdown": "# Heading\n- step one"},
            "secret_token",
            None,
        )

    assert result["page_id"] == "new_page_1"
    assert result["blocks_written"] == 2
    assert fake.requests[0][2]["json"]["properties"]["title"]["title"][0]["text"]["content"] == "New SOP"


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_github_review_pr_success():
    responses = [FakeResponse({
        "id": 999, "state": "APPROVED", "submitted_at": "2026-01-01T00:00:00Z",
        "html_url": "https://github.com/o/r/pull/1#review-999",
        "user": {"login": "agent-bot"},
    })]
    patcher, fake = patch_httpx_client(github_server, responses)
    with patcher:
        result = await github_server.TOOL_HANDLERS["review_pr"](
            {"owner": "o", "repo": "r", "pull_number": 1, "body": "LGTM", "event": "APPROVE"}, "ghp_token", None
        )

    assert result["state"] == "APPROVED"
    assert result["reviewer"] == "agent-bot"
    assert fake.requests[0][2]["json"]["event"] == "APPROVE"


@pytest.mark.asyncio
async def test_github_search_code_success():
    responses = [FakeResponse({
        "total_count": 1,
        "incomplete_results": False,
        "items": [{"name": "auth.py", "path": "app/auth.py", "repository": {"full_name": "o/r"},
                   "html_url": "https://github.com/o/r/blob/main/app/auth.py", "score": 1.0}],
    })]
    patcher, fake = patch_httpx_client(github_server, responses)
    with patcher:
        result = await github_server.TOOL_HANDLERS["search_code"]({"query": "auth repo:o/r"}, "ghp_token", None)

    assert result["total_count"] == 1
    assert result["results"][0]["repository"] == "o/r"
    assert fake.requests[0][2]["params"]["q"] == "auth repo:o/r"


@pytest.mark.asyncio
async def test_github_create_issue_with_labels_and_assignees():
    responses = [FakeResponse({
        "number": 42, "title": "Bug", "html_url": "https://github.com/o/r/issues/42",
        "state": "open", "created_at": "2026-01-01T00:00:00Z",
        "labels": [{"name": "bug"}],
    })]
    patcher, fake = patch_httpx_client(github_server, responses)
    with patcher:
        result = await github_server.TOOL_HANDLERS["create_issue"](
            {"owner": "o", "repo": "r", "title": "Bug", "labels": ["bug"], "assignees": ["dev1"]},
            "ghp_token",
            None,
        )

    assert result["issue_number"] == 42
    assert result["labels"] == ["bug"]
    assert fake.requests[0][2]["json"]["labels"] == ["bug"]
    assert fake.requests[0][2]["json"]["assignees"] == ["dev1"]


# ---------------------------------------------------------------------------
# LinkedIn
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_linkedin_draft_post_plain_text():
    responses = [
        FakeResponse({"sub": "member_123"}),  # userinfo
        FakeResponse({}, headers={"x-restli-id": "post_abc"}),  # ugcPosts
    ]
    patcher, fake = patch_httpx_client(linkedin_server, responses)
    with patcher:
        result = await linkedin_server.TOOL_HANDLERS["draft_post"]({"text": "Hello LinkedIn"}, "li_token", None)

    assert result["post_id"] == "post_abc"
    assert result["author_urn"] == "urn:li:person:member_123"
    assert result["has_article"] is False
    posted_payload = fake.requests[1][2]["json"]
    assert posted_payload["specificContent"]["com.linkedin.ugc.ShareContent"]["shareMediaCategory"] == "NONE"


@pytest.mark.asyncio
async def test_linkedin_draft_post_with_article_link():
    responses = [
        FakeResponse({"sub": "member_123"}),
        FakeResponse({}, headers={"x-restli-id": "post_xyz"}),
    ]
    patcher, fake = patch_httpx_client(linkedin_server, responses)
    with patcher:
        result = await linkedin_server.TOOL_HANDLERS["draft_post"](
            {"text": "Check this out", "article_url": "https://example.com", "article_title": "Example"},
            "li_token",
            None,
        )

    assert result["has_article"] is True
    share_content = fake.requests[1][2]["json"]["specificContent"]["com.linkedin.ugc.ShareContent"]
    assert share_content["shareMediaCategory"] == "ARTICLE"
    assert share_content["media"][0]["originalUrl"] == "https://example.com"


@pytest.mark.asyncio
async def test_linkedin_draft_post_truncates_long_text_preview():
    long_text = "x" * 150
    responses = [
        FakeResponse({"sub": "member_123"}),
        FakeResponse({}, headers={"x-restli-id": "post_1"}),
    ]
    patcher, _fake = patch_httpx_client(linkedin_server, responses)
    with patcher:
        result = await linkedin_server.TOOL_HANDLERS["draft_post"]({"text": long_text}, "li_token", None)

    assert result["text_preview"] == ("x" * 100) + "..."
