# Second Brain

API-first personal knowledge engine with embedded SurrealDB and agentic LLM loops.

## Setup

```bash
uv sync --all-extras
cp .env.example .env
# Edit .env with your API keys
```

## Run

```bash
uv run uvicorn second_brain.app:app --reload
```

## API

### `GET /health`

Health check.

### `POST /ingest`

Store knowledge. The ingest agent parses input, extracts entities, resolves references to existing knowledge, and builds graph relationships.

```json
{"text": "your notes or ideas here", "source": "cli"}
```

### `POST /recall`

Ask questions. The recall agent searches your knowledge base using full-text, vector, and graph traversal, then synthesizes an answer.

```json
{"question": "what do I know about X?"}
```

## Test

```bash
uv run pytest -v
```

## Stack

- Python, FastAPI, SurrealDB (embedded), PydanticAI
- Design doc: `docs/plans/2026-02-19-second-brain-design.md`
