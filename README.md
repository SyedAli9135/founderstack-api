# FounderStack AI — Backend (Orchestration Engine)

<p align="center">
  <em>The open-source Headless COO for Solo Founders.</em>
</p>

## Overview

FounderStack AI is an autonomous, multi-agent platform designed to execute the operational tasks of a solo founder—finance, engineering, marketing, and communications. 

Unlike traditional wrappers, FounderStack uses a stateful Graph orchestration engine (LangGraph) combined with the Model Context Protocol (FastMCP) to connect directly to your business tools safely and securely.

This repository contains the Python backend. For the Next.js Web UI, see the frontend repository.

## Features

- 🧠 **LangGraph Orchestration**: Stateful, agentic loops capable of reasoning, planning, and executing complex workflows.
- 🔌 **FastMCP Tool Gateway**: Native Model Context Protocol servers for Stripe, Slack, GitHub, and Notion.
- 🔐 **Zero-Trust Security**: Bring Your Own Key (BYOK) architecture. 
- 📚 **RAG & Knowledge Base**: Automatic document chunking, Cohere multilingual embedding, and Pinecone vector search.
- ⚡ **Real-Time Streaming**: Server-Sent Events (SSE) streaming of agent reasoning and tool calls.
- 👥 **Role-Based Access**: Multi-tenant architecture isolated by Postgres Row-Level Security (RLS).

## Quickstart (Local Dev)

We use `uv` for ultra-fast dependency management and `docker-compose` for our local database state.

1. **Prerequisites**: Ensure you have Python 3.12, Docker, and `uv` installed.
   * *Install uv on Mac/Linux:* `curl -LsSf https://astral.sh/uv/install.sh | sh`

2. **Clone & Install**:
   ```bash
   git clone https://github.com/yourusername/founderstack-api.git
   cd founderstack-api
   uv sync
   ```

3. **Environment**: 
   Copy the environment variables template:
   ```bash
   cp .env.example .env
   ```
   *(Fill in your Anthropic, Clerk, and Pinecone keys into `.env`).*

4. **Start Local Services (Postgres & Redis)**: 
   ```bash
   docker compose -f docker-compose.local.yml up -d
   ```

5. **Run Database Migrations**:
   This applies the complete 18-table database schema locally:
   ```bash
   uv run alembic upgrade head
   ```

6. **Start the API**:
   ```bash
   uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

7. **Verify Setup**:
   Visit [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health). You should receive a payload indicating both the `database` and `redis` are `healthy`.

## License

**GNU Affero General Public License v3.0 (AGPLv3)**

FounderStack AI is open-source. Under the AGPLv3 license, you are free to use, modify, and distribute this software. However, if you modify the code and provide it as a commercial SaaS or network service, you **must** release your modified source code under the same AGPLv3 license.
