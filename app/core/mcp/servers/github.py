"""
GitHub MCP Server — Engineering tools for FounderStack agents.

Provides tools to review pull requests, search code, and create issues.
FastMCP stubs handle schema/discovery; the MCPGateway calls the underlying
async functions directly with the decrypted PAT.
"""

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from typing import Optional, List

mcp = FastMCP(
    "github",
    instructions="Engineering tools for reviewing PRs, searching code, and managing GitHub issues.",
)

SERVICE = "github"
GH_API = "https://api.github.com"
GH_ACCEPT = "application/vnd.github+json"
GH_VERSION = "2022-11-28"


# ---------------------------------------------------------------------------
# Input Schemas
# ---------------------------------------------------------------------------

class ReviewPRInput(BaseModel):
    owner: str = Field(..., description="GitHub repository owner (user or org name).")
    repo: str = Field(..., description="Repository name (without owner prefix).")
    pull_number: int = Field(..., description="Pull request number to review.")
    event: str = Field(default="COMMENT", description="Review action: 'APPROVE', 'REQUEST_CHANGES', or 'COMMENT'.")
    body: str = Field(..., description="Review comment body. Required for all event types.")


class SearchCodeInput(BaseModel):
    query: str = Field(
        ...,
        description=(
            "GitHub code search query with qualifiers: repo:owner/repo, language:python, filename:main.py. "
            "Example: 'auth login repo:myorg/api language:python'."
        ),
    )
    per_page: int = Field(default=10, ge=1, le=30, description="Number of results to return (1–30).")


class CreateIssueInput(BaseModel):
    owner: str = Field(..., description="GitHub repository owner.")
    repo: str = Field(..., description="Repository name.")
    title: str = Field(..., description="Issue title.")
    body: Optional[str] = Field(default=None, description="Issue body (markdown supported).")
    labels: Optional[List[str]] = Field(default=None, description="List of label names to apply.")
    assignees: Optional[List[str]] = Field(default=None, description="GitHub usernames to assign.")
    milestone: Optional[int] = Field(default=None, description="Milestone number to associate.")


# ---------------------------------------------------------------------------
# Core async functions
# ---------------------------------------------------------------------------

def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": GH_ACCEPT,
        "X-GitHub-Api-Version": GH_VERSION,
    }


async def _review_pr(params: ReviewPRInput, token: str) -> dict:
    url = f"{GH_API}/repos/{params.owner}/{params.repo}/pulls/{params.pull_number}/reviews"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=_gh_headers(token),
                                  json={"body": params.body, "event": params.event})
        resp.raise_for_status()
        review = resp.json()

    return {
        "review_id": review["id"],
        "state": review["state"],
        "submitted_at": review.get("submitted_at"),
        "pr_url": review.get("html_url"),
        "reviewer": review.get("user", {}).get("login"),
    }


async def _search_code(params: SearchCodeInput, token: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GH_API}/search/code",
            headers=_gh_headers(token),
            params={"q": params.query, "per_page": str(params.per_page)},
        )
        resp.raise_for_status()
        data = resp.json()

    return {
        "total_count": data.get("total_count", 0),
        "results": [
            {
                "name": item["name"],
                "path": item["path"],
                "repository": item["repository"]["full_name"],
                "url": item["html_url"],
                "score": item.get("score"),
            }
            for item in data.get("items", [])
        ],
        "incomplete_results": data.get("incomplete_results", False),
    }


async def _create_issue(params: CreateIssueInput, token: str) -> dict:
    url = f"{GH_API}/repos/{params.owner}/{params.repo}/issues"
    payload: dict = {"title": params.title}
    if params.body:
        payload["body"] = params.body
    if params.labels:
        payload["labels"] = params.labels
    if params.assignees:
        payload["assignees"] = params.assignees
    if params.milestone:
        payload["milestone"] = params.milestone

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=_gh_headers(token), json=payload)
        resp.raise_for_status()
        issue = resp.json()

    return {
        "issue_number": issue["number"],
        "title": issue["title"],
        "url": issue["html_url"],
        "state": issue["state"],
        "created_at": issue["created_at"],
        "labels": [lbl["name"] for lbl in issue.get("labels", [])],
    }


# ---------------------------------------------------------------------------
# FastMCP tool stubs — registered for schema/discovery only
# ---------------------------------------------------------------------------

@mcp.tool()
async def review_pr(owner: str, repo: str, pull_number: int, body: str, event: str = "COMMENT") -> dict:
    """
    Submit a review on a GitHub pull request (APPROVE, REQUEST_CHANGES, or COMMENT).

    Agents use this to programmatically review code changes. APPROVE marks the PR
    ready to merge; REQUEST_CHANGES blocks the merge until addressed. COMMENT leaves
    inline feedback without blocking. Returns the review ID, state, and a link to the PR.
    """
    raise NotImplementedError("Use MCPGateway.execute_tool() for in-process execution.")


@mcp.tool()
async def search_code(query: str, per_page: int = 10) -> dict:
    """
    Search for code across GitHub repositories using the code search API.

    Supports GitHub's full qualifier syntax (repo:, language:, filename:, extension:).
    Returns matching file paths, repository names, and direct URLs. Useful for finding
    existing implementations, security patterns, or understanding codebase structure
    before planning changes.
    """
    raise NotImplementedError("Use MCPGateway.execute_tool() for in-process execution.")


@mcp.tool()
async def create_issue(
    owner: str,
    repo: str,
    title: str,
    body: Optional[str] = None,
    labels: Optional[List[str]] = None,
    assignees: Optional[List[str]] = None,
    milestone: Optional[int] = None,
) -> dict:
    """
    Create a new GitHub issue in a repository with title, description, labels, and assignees.

    Agents use this to log bugs, feature requests, or action items discovered during
    workflow execution. Returns the issue number, URL, and creation timestamp.
    Supports attaching labels, assigning team members, and linking to milestones.
    """
    raise NotImplementedError("Use MCPGateway.execute_tool() for in-process execution.")


# ---------------------------------------------------------------------------
# Tool dispatch table
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {
    "review_pr": lambda params, token, _db: _review_pr(ReviewPRInput(**params), token),
    "search_code": lambda params, token, _db: _search_code(SearchCodeInput(**params), token),
    "create_issue": lambda params, token, _db: _create_issue(CreateIssueInput(**params), token),
}
