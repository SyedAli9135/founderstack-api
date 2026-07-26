"""
Shared test doubles for mocking `httpx.AsyncClient` calls made by MCP server modules.

Each MCP server module (app/core/mcp/servers/*.py) does `import httpx` and calls
`async with httpx.AsyncClient() as client: ...`. These helpers let tests replace
`httpx.AsyncClient` with a fake that returns pre-queued responses, in call order,
without touching the network.
"""

from unittest.mock import patch

import httpx


class FakeResponse:
    """Minimal stand-in for httpx.Response used by MCP server handlers."""

    def __init__(self, json_data: dict | None = None, status_code: int = 200, headers: dict | None = None):
        self._json_data = json_data if json_data is not None else {}
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.test")
            raise httpx.HTTPStatusError(
                f"Mock error {self.status_code}", request=request, response=self
            )

    def json(self) -> dict:
        return self._json_data


class FakeAsyncClient:
    """
    Drop-in replacement for `httpx.AsyncClient`.

    Responses are consumed in FIFO order regardless of which method/URL is called,
    which matches how the MCP server functions issue a fixed, ordered sequence of
    requests per tool call. Every request is recorded in `.requests` for assertions.
    """

    def __init__(self, responses: list[FakeResponse]):
        self._responses = list(responses)
        self.requests: list[tuple[str, str, dict]] = []

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def _consume(self, method: str, url: str, **kwargs) -> FakeResponse:
        self.requests.append((method, url, kwargs))
        if not self._responses:
            raise AssertionError(f"No fake response queued for {method} {url}")
        return self._responses.pop(0)

    async def get(self, url: str, **kwargs) -> FakeResponse:
        return await self._consume("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> FakeResponse:
        return await self._consume("POST", url, **kwargs)


def patch_httpx_client(module, responses: list[FakeResponse]):
    """
    Return (patcher, fake_client) for replacing `module.httpx.AsyncClient`.

    Usage:
        patcher, fake = patch_httpx_client(stripe_server, [FakeResponse({...})])
        with patcher:
            result = await stripe_server._get_mrr("sk_test_123")
        assert fake.requests[0][0] == "GET"
    """
    fake_client = FakeAsyncClient(responses)
    patcher = patch.object(module.httpx, "AsyncClient", return_value=fake_client)
    return patcher, fake_client
