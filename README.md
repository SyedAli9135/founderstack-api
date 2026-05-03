# FounderStack AI — Backend (Orchestration Engine)

<p align="center">
  <em>The open-source Headless COO for Solo Founders.</em>
</p>

## Overview

FounderStack AI is an autonomous, multi-agent platform designed to execute the operational tasks of a solo founder—finance, engineering, marketing, and communications. 

Unlike traditional wrappers, FounderStack uses a stateful Graph orchestration engine (LangGraph) combined with the Model Context Protocol (FastMCP) to connect directly to your business tools safely and securely.

This repository contains the Python backend. For the Next.js Web UI, see the [Frontend Repository](link_to_frontend).

## Features

- �� **LangGraph Orchestration**: Stateful, agentic loops capable of reasoning, planning, and executing complex workflows.
- 🔌 **FastMCP Tool Gateway**: Native Model Context Protocol servers for Stripe, Slack, GitHub, and Notion.
- 🔐 **Zero-Trust Security**: Bring Your Own Key (BYOK) architecture. API keys are encrypted at rest; OAuth tokens never enter the LLM context.
- 📚 **RAG & Knowledge Base**: Automatic document chunking, Cohere multilingual embedding, and Pinecone vector search.
- ⚡ **Real-Time Streaming**: Server-Sent Events (SSE) streaming of agent reasoning, tool calls, and human-in-the-loop approval gates.
- 👥 **Role-Based Access**: Multi-tenant architecture isolated by Postgres Row-Level Security (RLS).

## Tech Stack

- **Framework**: FastAPI (Python 3.12)
- **Database**: PostgreSQL 16 (AWS RDS) + asyncpg
- **Orchestration**: LangGraph Cloud / LangChain Base
- **LLM Routing**: LiteLLM (Anthropic Claude 3.5 Sonnet primarily)
- **Vector DB**: Pinecone + Cohere Embed v4
- **State/Cache**: Redis (Upstash)

## Quickstart (Local Dev)

1. **Prerequisites**: Ensure you have Python 3.12, Docker, and `poetry` installed.
2. **Clone & Install**:
   ```bash
   git clone https://github.com/yourusername/founderstack-backend.git
   cd founderstack-backend
   poetry install
   ```
3. **Environment**: 
   Copy `.env.example` to `.env` and fill in your keys (Anthropic, Clerk, Pinecone, Nango).
4. **Start Local Services**: 
   ```bash
   docker-compose -f docker-compose.local.yml up -d
   ```
5. **Run Migrations**:
   ```bash
   poetry run alembic upgrade head
   ```
6. **Start the API**:
   ```bash
   poetry run uvicorn app.main:app --reload
   ```

## Contributing

We welcome contributions! Please review our `CONTRIBUTING.md` before submitting a Pull Request.

## License

**GNU Affero General Public License v3.0 (AGPLv3)**

FounderStack AI is open-source, promoting transparency and trust in heavily-permissioned AI workflows. Under the AGPLv3 license, you are free to use, modify, and distribute this software. However, if you modify the code and provide it as a commercial SaaS or network service, you **must** release your modified source code under the same AGPLv3 license.

For commercial licenses without the copyleft restriction, please contact founders@founderstack.ai.
