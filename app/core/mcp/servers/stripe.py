"""
Stripe MCP Server — Finance tools for FounderStack agents.

Provides tools to manage Stripe subscriptions, invoices, payments, and MRR.
Tools are registered with FastMCP for schema discovery / Pinecone seeding.
For in-process execution the gateway calls the underlying async functions directly,
passing org_id and db as runtime arguments that are NOT part of the MCP schema.
"""

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from typing import Optional

mcp = FastMCP(
    "stripe",
    instructions="Finance tools for managing Stripe subscriptions, invoices, payments, and MRR.",
)

SERVICE = "stripe"


# ---------------------------------------------------------------------------
# Input Schemas (JSON-serializable — these become the MCP tool inputSchema)
# ---------------------------------------------------------------------------

class CreateInvoiceInput(BaseModel):
    customer_id: str = Field(..., description="Stripe customer ID (cus_xxx) to create the invoice for.")
    amount_cents: int = Field(..., description="Invoice amount in cents (e.g., 5000 = $50.00).")
    currency: str = Field(default="usd", description="Three-letter ISO currency code (default: usd).")
    description: Optional[str] = Field(default=None, description="Optional description for the invoice line item.")
    auto_advance: bool = Field(default=True, description="If true, Stripe will automatically finalize the invoice.")


class ListCustomersInput(BaseModel):
    limit: int = Field(default=10, ge=1, le=100, description="Maximum number of customers to return (1–100).")
    email: Optional[str] = Field(default=None, description="Optional email to filter customers by.")


class RefundPaymentInput(BaseModel):
    payment_intent_id: str = Field(..., description="Stripe PaymentIntent ID (pi_xxx) to refund.")
    amount_cents: Optional[int] = Field(default=None, description="Partial refund amount in cents. Omit for full refund.")
    reason: Optional[str] = Field(default=None, description="Refund reason: 'duplicate', 'fraudulent', or 'requested_by_customer'.")


class GetMrrInput(BaseModel):
    pass  # No parameters needed


# ---------------------------------------------------------------------------
# Core async tool functions (called by MCPGateway at runtime with org_id + db)
# ---------------------------------------------------------------------------

async def _create_invoice(params: CreateInvoiceInput, api_key: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient() as client:
        item_resp = await client.post(
            "https://api.stripe.com/v1/invoiceitems",
            headers=headers,
            data={
                "customer": params.customer_id,
                "amount": str(params.amount_cents),
                "currency": params.currency,
                "description": params.description or "FounderStack agent-generated invoice",
            },
        )
        item_resp.raise_for_status()

        inv_resp = await client.post(
            "https://api.stripe.com/v1/invoices",
            headers=headers,
            data={
                "customer": params.customer_id,
                "auto_advance": str(params.auto_advance).lower(),
            },
        )
        inv_resp.raise_for_status()
        invoice = inv_resp.json()

    return {
        "invoice_id": invoice["id"],
        "status": invoice["status"],
        "amount_due": invoice["amount_due"],
        "currency": invoice["currency"],
        "hosted_invoice_url": invoice.get("hosted_invoice_url"),
    }


async def _list_customers(params: ListCustomersInput, api_key: str) -> dict:
    query: dict = {"limit": str(params.limit)}
    if params.email:
        query["email"] = params.email

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.stripe.com/v1/customers",
            headers={"Authorization": f"Bearer {api_key}"},
            params=query,
        )
        resp.raise_for_status()
        data = resp.json()

    return {
        "customers": [
            {
                "id": c["id"],
                "email": c.get("email"),
                "name": c.get("name"),
                "created": c["created"],
                "delinquent": c.get("delinquent", False),
            }
            for c in data.get("data", [])
        ],
        "has_more": data.get("has_more", False),
    }


async def _refund_payment(params: RefundPaymentInput, api_key: str) -> dict:
    refund_data: dict = {"payment_intent": params.payment_intent_id}
    if params.amount_cents:
        refund_data["amount"] = str(params.amount_cents)
    if params.reason:
        refund_data["reason"] = params.reason

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.stripe.com/v1/refunds",
            headers={"Authorization": f"Bearer {api_key}"},
            data=refund_data,
        )
        resp.raise_for_status()
        refund = resp.json()

    return {
        "refund_id": refund["id"],
        "amount_refunded": refund["amount"],
        "currency": refund["currency"],
        "status": refund["status"],
    }


async def _get_mrr(api_key: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    mrr_cents = 0
    active_count = 0
    has_more = True
    starting_after: Optional[str] = None

    async with httpx.AsyncClient() as client:
        while has_more:
            query: dict = {"status": "active", "limit": "100"}
            if starting_after:
                query["starting_after"] = starting_after

            resp = await client.get(
                "https://api.stripe.com/v1/subscriptions",
                headers=headers,
                params=query,
            )
            resp.raise_for_status()
            data = resp.json()

            for sub in data.get("data", []):
                active_count += 1
                for item in sub.get("items", {}).get("data", []):
                    price = item.get("price", {})
                    unit_amount = price.get("unit_amount") or 0
                    interval = price.get("recurring", {}).get("interval", "month")
                    interval_count = price.get("recurring", {}).get("interval_count", 1)
                    quantity = item.get("quantity", 1)
                    if interval == "year":
                        monthly = unit_amount / (12 * interval_count)
                    elif interval == "week":
                        monthly = unit_amount * (4.33 / interval_count)
                    elif interval == "day":
                        monthly = unit_amount * (30.4 / interval_count)
                    else:
                        monthly = unit_amount / interval_count
                    mrr_cents += int(monthly * quantity)

            has_more = data.get("has_more", False)
            if has_more and data["data"]:
                starting_after = data["data"][-1]["id"]

    return {
        "mrr_cents": mrr_cents,
        "mrr_usd": round(mrr_cents / 100, 2),
        "active_subscriptions": active_count,
    }


# ---------------------------------------------------------------------------
# FastMCP tool stubs — registered for schema/discovery only.
# Docstrings power semantic search in Pinecone.
# ---------------------------------------------------------------------------

@mcp.tool()
async def create_invoice(customer_id: str, amount_cents: int, currency: str = "usd",
                          description: Optional[str] = None, auto_advance: bool = True) -> dict:
    """
    Create a Stripe invoice for a customer and optionally auto-finalize it.

    Accepts a Stripe customer ID and an amount in cents. Creates an invoice item
    and a corresponding invoice. If auto_advance is true, Stripe will finalize the
    invoice automatically. Returns the invoice ID, status, amount due, and a
    hosted URL the customer can use to view/pay the invoice.
    """
    raise NotImplementedError("Use MCPGateway.execute_tool() for in-process execution.")


@mcp.tool()
async def list_customers(limit: int = 10, email: Optional[str] = None) -> dict:
    """
    List Stripe customers with optional email filtering.

    Returns up to `limit` customers from the Stripe account, each with their ID,
    email address, name, creation date, and delinquency status. Useful for
    looking up a customer before creating invoices or refunds.
    """
    raise NotImplementedError("Use MCPGateway.execute_tool() for in-process execution.")


@mcp.tool()
async def refund_payment(payment_intent_id: str, amount_cents: Optional[int] = None,
                          reason: Optional[str] = None) -> dict:
    """
    Issue a full or partial refund for a Stripe PaymentIntent.

    Refunds all or part of a captured payment. Provide a reason ('duplicate',
    'fraudulent', or 'requested_by_customer') for audit purposes. Returns the
    refund ID, amount refunded, and final status.
    """
    raise NotImplementedError("Use MCPGateway.execute_tool() for in-process execution.")


@mcp.tool()
async def get_mrr() -> dict:
    """
    Calculate Monthly Recurring Revenue (MRR) from all active Stripe subscriptions.

    Iterates every active subscription, normalizes billing intervals (daily, weekly,
    yearly) to a monthly equivalent, and sums the result. Returns total MRR in both
    cents and USD, plus the active subscription count. Essential for finance reporting.
    """
    raise NotImplementedError("Use MCPGateway.execute_tool() for in-process execution.")


# ---------------------------------------------------------------------------
# Tool dispatch table — used by MCPGateway for direct async execution
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {
    "create_invoice": lambda params, token, _db: _create_invoice(
        CreateInvoiceInput(**params), token
    ),
    "list_customers": lambda params, token, _db: _list_customers(
        ListCustomersInput(**params), token
    ),
    "refund_payment": lambda params, token, _db: _refund_payment(
        RefundPaymentInput(**params), token
    ),
    "get_mrr": lambda params, token, _db: _get_mrr(token),
}
