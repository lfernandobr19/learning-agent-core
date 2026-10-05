# learning-agent (Ravenna core)

Local learning / agent platform with:

- **FastAPI** REST API
- **MCP** server (`learning-agent-mcp`)
- **RAG** via ChromaDB
- Multi-provider LLM routing (teacher/student, Ollama/OpenAI-compatible endpoints)
- Autonomy / learning-loop agents, quizzes, and benchmarks
- Optional Telegram channel and cloud sync hooks

This repository is a **sanitized core** extracted from a personal monorepo. Employer-specific integrations and data were removed.

## Requirements

- Python 3.11 or 3.12

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
learning-agent-api
```

MCP:

```bash
learning-agent-mcp
```

## Layout

- `learning_agent/` — package (API, MCP, RAG, agent core)
- `tests/` — pytest suite
- `agents/` — curricula / archetypes
- `integrations/` — editor MCP examples

## Privacy

Private repository. Never commit `.env`, databases, or customer/employer material.
