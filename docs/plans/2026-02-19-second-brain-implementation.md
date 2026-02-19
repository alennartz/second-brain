# Second Brain Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an API-first personal knowledge engine with SurrealDB embedded and PydanticAI agentic loops.

**Architecture:** FastAPI app with two PydanticAI agents (Ingest, Recall) sharing an embedded SurrealDB instance. Agents have tools for reading/writing knowledge graph nodes and edges. Embedding utility generates vectors via configurable model.

**Tech Stack:** Python 3.12+, FastAPI, SurrealDB (embedded via `surrealdb` PyPI package), PydanticAI (agent framework), `uv` (package manager)

**Design doc:** `docs/plans/2026-02-19-second-brain-design.md`

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/second_brain/__init__.py`
- Create: `src/second_brain/config.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `.python-version`

**Step 1: Initialize project with uv**

Run: `uv init --lib --name second-brain`

**Step 2: Configure pyproject.toml**

```toml
[project]
name = "second-brain"
version = "0.1.0"
description = "API-first personal knowledge engine"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.34.0",
    "surrealdb>=0.4.0",
    "pydantic-ai>=1.0.0",
    "pydantic-settings>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.25.0",
    "httpx>=0.28.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Step 3: Create config module**

```python
# src/second_brain/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_path: str = "data/brain.db"
    embedding_model: str = "openai:text-embedding-3-small"
    reasoning_model: str = "openai:gpt-4o-mini"
    embedding_dimensions: int = 1536

    model_config = {"env_prefix": "BRAIN_", "env_file": ".env"}


settings = Settings()
```

**Step 4: Create .env.example**

```
BRAIN_DB_PATH=data/brain.db
BRAIN_EMBEDDING_MODEL=openai:text-embedding-3-small
BRAIN_REASONING_MODEL=openai:gpt-4o-mini
BRAIN_EMBEDDING_DIMENSIONS=1536
OPENAI_API_KEY=sk-...
```

**Step 5: Create .gitignore**

```
__pycache__/
*.pyc
.env
data/
.venv/
dist/
*.egg-info/
.pytest_cache/
```

**Step 6: Create .python-version**

```
3.12
```

**Step 7: Create conftest.py with shared fixtures**

```python
# tests/conftest.py
import pytest
from surrealdb import AsyncSurreal


@pytest.fixture
async def db():
    """In-memory SurrealDB for tests."""
    async with AsyncSurreal("mem://") as db:
        await db.use("test", "test")
        yield db
```

**Step 8: Install dependencies**

Run: `uv sync --all-extras`

**Step 9: Run pytest to verify setup**

Run: `uv run pytest --collect-only`
Expected: no errors, 0 tests collected

**Step 10: Commit**

```bash
git add -A
git commit -m "feat: project scaffolding with uv, FastAPI, SurrealDB, PydanticAI"
```

---

### Task 2: Database Schema and Initialization

**Files:**
- Create: `src/second_brain/db.py`
- Create: `tests/test_db.py`

**Step 1: Write the failing test**

```python
# tests/test_db.py
import pytest
from second_brain.db import init_schema


async def test_init_schema_creates_tables(db):
    await init_schema(db)

    # Verify note table exists by inserting and selecting
    await db.query("CREATE note SET content = 'test', source = 'test'")
    result = await db.query("SELECT * FROM note")
    assert len(result[0]["result"]) == 1


async def test_init_schema_creates_entity_table(db):
    await init_schema(db)

    await db.query("CREATE entity SET name = 'Python', type = 'concept'")
    result = await db.query("SELECT * FROM entity")
    assert len(result[0]["result"]) == 1


async def test_init_schema_is_idempotent(db):
    await init_schema(db)
    await init_schema(db)  # Should not raise

    await db.query("CREATE note SET content = 'test', source = 'test'")
    result = await db.query("SELECT * FROM note")
    assert len(result[0]["result"]) == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'second_brain.db'`

**Step 3: Implement db module**

```python
# src/second_brain/db.py
from surrealdb import AsyncSurreal

from second_brain.config import settings


async def get_db() -> AsyncSurreal:
    """Create and return an embedded SurrealDB connection."""
    db = AsyncSurreal(f"surrealkv://{settings.db_path}")
    await db.use("brain", "brain")
    await init_schema(db)
    return db


async def init_schema(db: AsyncSurreal) -> None:
    """Define tables, fields, and indexes. Idempotent."""
    await db.query("""
        -- Note table
        DEFINE TABLE IF NOT EXISTS note SCHEMALESS;
        DEFINE FIELD IF NOT EXISTS content ON note TYPE string;
        DEFINE FIELD IF NOT EXISTS summary ON note TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS embedding ON note TYPE option<array<float>>;
        DEFINE FIELD IF NOT EXISTS source ON note TYPE string;
        DEFINE FIELD IF NOT EXISTS created_at ON note TYPE datetime DEFAULT time::now();
        DEFINE FIELD IF NOT EXISTS updated_at ON note TYPE datetime DEFAULT time::now();

        -- Entity table
        DEFINE TABLE IF NOT EXISTS entity SCHEMALESS;
        DEFINE FIELD IF NOT EXISTS name ON entity TYPE string;
        DEFINE FIELD IF NOT EXISTS type ON entity TYPE string;
        DEFINE FIELD IF NOT EXISTS description ON entity TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS embedding ON entity TYPE option<array<float>>;

        -- Edge tables
        DEFINE TABLE IF NOT EXISTS references SCHEMALESS;
        DEFINE TABLE IF NOT EXISTS relates_to SCHEMALESS;
        DEFINE FIELD IF NOT EXISTS context ON relates_to TYPE option<string>;
        DEFINE TABLE IF NOT EXISTS derived_from SCHEMALESS;

        -- Full-text indexes
        DEFINE INDEX IF NOT EXISTS note_content_fts ON note FIELDS content
            FULLTEXT ANALYZER simple BM25;
        DEFINE INDEX IF NOT EXISTS entity_name_fts ON entity FIELDS name
            FULLTEXT ANALYZER simple BM25;
    """)
```

Note: Vector indexes (HNSW) are added in Task 3 after we confirm the embedding dimension from config.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add src/second_brain/db.py tests/test_db.py
git commit -m "feat: database schema with note, entity, and edge tables"
```

---

### Task 3: Embedding Utility

**Files:**
- Create: `src/second_brain/embedding.py`
- Create: `tests/test_embedding.py`

**Step 1: Write the failing test**

We test with a mock to avoid real API calls. The embedding function should call PydanticAI's model and return a list of floats.

```python
# tests/test_embedding.py
import pytest
from unittest.mock import AsyncMock, patch

from second_brain.embedding import embed_text, init_vector_indexes


async def test_embed_text_returns_vector():
    fake_vector = [0.1] * 1536

    with patch("second_brain.embedding._get_embedding", new_callable=AsyncMock) as mock:
        mock.return_value = fake_vector
        result = await embed_text("hello world")

    assert len(result) == 1536
    assert isinstance(result, list)
    assert all(isinstance(x, float) for x in result)


async def test_init_vector_indexes(db):
    await init_vector_indexes(db, dimensions=3)

    # Should not raise on second call
    await init_vector_indexes(db, dimensions=3)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_embedding.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement embedding module**

```python
# src/second_brain/embedding.py
from surrealdb import AsyncSurreal

from second_brain.config import settings

# Late-initialized by configure_embedding()
_embed_fn = None


async def _get_embedding(text: str) -> list[float]:
    """Get embedding from configured model. Override in tests."""
    if _embed_fn is not None:
        return await _embed_fn(text)

    from pydantic_ai.models import infer_model

    model = infer_model(settings.embedding_model)
    # Use the model's embedding endpoint
    # PydanticAI doesn't have a built-in embed() — we use the provider SDK directly
    # For now, use OpenAI's embedding API via httpx
    import httpx
    import os

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={
                "model": settings.embedding_model.split(":")[-1],
                "input": text,
            },
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


async def embed_text(text: str) -> list[float]:
    """Generate an embedding vector for the given text."""
    return await _get_embedding(text)


async def init_vector_indexes(db: AsyncSurreal, dimensions: int | None = None) -> None:
    """Define HNSW vector indexes. Idempotent."""
    dim = dimensions or settings.embedding_dimensions
    await db.query(f"""
        DEFINE INDEX IF NOT EXISTS note_embedding_hnsw ON note
            FIELDS embedding HNSW DIMENSION {dim} DIST COSINE;
        DEFINE INDEX IF NOT EXISTS entity_embedding_hnsw ON entity
            FIELDS embedding HNSW DIMENSION {dim} DIST COSINE;
    """)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_embedding.py -v`
Expected: 2 PASSED

**Step 5: Commit**

```bash
git add src/second_brain/embedding.py tests/test_embedding.py
git commit -m "feat: embedding utility with vector index initialization"
```

---

### Task 4: Recall Agent Tools (Read-Only DB Tools)

**Files:**
- Create: `src/second_brain/tools/recall_tools.py`
- Create: `tests/test_recall_tools.py`

These are the SurrealDB query functions that the Recall Agent will use as PydanticAI tools. We build and test them as plain async functions first, then wire them into the agent in Task 6.

**Step 1: Write the failing tests**

```python
# tests/test_recall_tools.py
import pytest
from second_brain.db import init_schema
from second_brain.tools.recall_tools import (
    full_text_search,
    get_connections,
    get_node,
    graph_traverse,
    vector_search,
)


@pytest.fixture
async def seeded_db(db):
    """DB with schema and sample data."""
    await init_schema(db)
    await db.query("""
        CREATE note:1 SET content = 'Spaced repetition improves long-term memory',
            summary = 'spaced repetition for memory', source = 'cli',
            embedding = [0.1, 0.2, 0.3];
        CREATE note:2 SET content = 'GTD is a productivity methodology',
            summary = 'GTD methodology', source = 'cli',
            embedding = [0.4, 0.5, 0.6];
        CREATE entity:sr SET name = 'spaced repetition', type = 'concept';
        CREATE entity:gtd SET name = 'GTD', type = 'concept';
        RELATE note:1->references->entity:sr;
        RELATE note:2->references->entity:gtd;
        RELATE entity:sr->relates_to->entity:gtd SET context = 'both are learning methods';
    """)
    return db


async def test_get_node(seeded_db):
    result = await get_node(seeded_db, "note:1")
    assert "Spaced repetition" in result["content"]


async def test_get_connections(seeded_db):
    result = await get_connections(seeded_db, "entity:sr")
    assert len(result) > 0


async def test_full_text_search(seeded_db):
    results = await full_text_search(seeded_db, "note", "repetition")
    assert len(results) >= 1


async def test_graph_traverse(seeded_db):
    results = await graph_traverse(seeded_db, "note:1", depth=2)
    assert len(results) >= 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_recall_tools.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement recall tools**

```python
# src/second_brain/tools/recall_tools.py
from surrealdb import AsyncSurreal


async def vector_search(db: AsyncSurreal, table: str, query_embedding: list[float], k: int = 5) -> list[dict]:
    """Find the k nearest notes/entities by vector similarity."""
    result = await db.query(
        f"SELECT *, vector::similarity::cosine(embedding, $vec) AS score "
        f"FROM {table} WHERE embedding <|{k}|> $vec "
        f"ORDER BY score DESC",
        {"vec": query_embedding},
    )
    return result[0]["result"]


async def full_text_search(db: AsyncSurreal, table: str, query: str, limit: int = 10) -> list[dict]:
    """Search notes or entities by full-text match using BM25."""
    field = "content" if table == "note" else "name"
    result = await db.query(
        f"SELECT *, search::score(1) AS score FROM {table} "
        f"WHERE {field} @1@ $query "
        f"ORDER BY score DESC LIMIT $limit",
        {"query": query, "limit": limit},
    )
    return result[0]["result"]


async def get_node(db: AsyncSurreal, record_id: str) -> dict:
    """Get a single node by its record ID (e.g., 'note:1' or 'entity:sr')."""
    result = await db.query(f"SELECT * FROM {record_id}")
    rows = result[0]["result"]
    if not rows:
        return {}
    return rows[0]


async def get_connections(db: AsyncSurreal, record_id: str) -> list[dict]:
    """Get all edges connected to a node (both incoming and outgoing)."""
    result = await db.query(
        f"SELECT * FROM {record_id}->references.* "
        f"UNION SELECT * FROM {record_id}<-references.* "
        f"UNION SELECT * FROM {record_id}->relates_to.* "
        f"UNION SELECT * FROM {record_id}<-relates_to.* "
        f"UNION SELECT * FROM {record_id}->derived_from.* "
        f"UNION SELECT * FROM {record_id}<-derived_from.*"
    )
    return result[0]["result"]


async def graph_traverse(db: AsyncSurreal, record_id: str, depth: int = 2) -> list[dict]:
    """Traverse the graph from a starting node up to N hops."""
    # Use SurrealDB's graph traversal syntax
    # ->references-> goes from note to entity, then ->relates_to-> goes entity to entity
    arrows = "->?->" * depth
    result = await db.query(
        f"SELECT * FROM {record_id}{arrows}*"
    )
    return result[0]["result"]
```

Also create the `__init__.py`:

```python
# src/second_brain/tools/__init__.py
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_recall_tools.py -v`
Expected: 4 PASSED (vector_search is not tested here because it needs HNSW index with proper dimensions; it'll be integration-tested in Task 6)

**Step 5: Commit**

```bash
git add src/second_brain/tools/ tests/test_recall_tools.py
git commit -m "feat: recall agent tools — search, graph traversal, node access"
```

---

### Task 5: Ingest Agent Tools (Write DB Tools)

**Files:**
- Create: `src/second_brain/tools/ingest_tools.py`
- Create: `tests/test_ingest_tools.py`

**Step 1: Write the failing tests**

```python
# tests/test_ingest_tools.py
import pytest
from second_brain.db import init_schema
from second_brain.tools.ingest_tools import (
    create_edge,
    create_entity,
    create_note,
    update_node,
)


@pytest.fixture
async def schema_db(db):
    await init_schema(db)
    return db


async def test_create_note(schema_db):
    note = await create_note(schema_db, content="Test note", source="cli")
    assert note["content"] == "Test note"
    assert note["source"] == "cli"
    assert "id" in note


async def test_create_entity(schema_db):
    entity = await create_entity(schema_db, name="Python", type="concept")
    assert entity["name"] == "Python"
    assert entity["type"] == "concept"


async def test_create_edge(schema_db):
    await schema_db.query("CREATE note:1 SET content = 'test', source = 'cli'")
    await schema_db.query("CREATE entity:py SET name = 'Python', type = 'concept'")

    edge = await create_edge(schema_db, from_id="note:1", edge_table="references", to_id="entity:py")
    assert edge is not None


async def test_update_node(schema_db):
    await schema_db.query("CREATE note:1 SET content = 'old', source = 'cli'")

    updated = await update_node(schema_db, record_id="note:1", fields={"summary": "new summary"})
    assert updated["summary"] == "new summary"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ingest_tools.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement ingest tools**

```python
# src/second_brain/tools/ingest_tools.py
from surrealdb import AsyncSurreal


async def create_note(
    db: AsyncSurreal,
    content: str,
    source: str,
    summary: str | None = None,
    embedding: list[float] | None = None,
) -> dict:
    """Create a new note in the knowledge base."""
    data = {"content": content, "source": source}
    if summary:
        data["summary"] = summary
    if embedding:
        data["embedding"] = embedding
    result = await db.create("note", data)
    return result[0] if isinstance(result, list) else result


async def create_entity(
    db: AsyncSurreal,
    name: str,
    type: str,
    description: str | None = None,
    embedding: list[float] | None = None,
) -> dict:
    """Create a new entity (concept, person, project, etc.)."""
    data = {"name": name, "type": type}
    if description:
        data["description"] = description
    if embedding:
        data["embedding"] = embedding
    result = await db.create("entity", data)
    return result[0] if isinstance(result, list) else result


async def create_edge(
    db: AsyncSurreal,
    from_id: str,
    edge_table: str,
    to_id: str,
    context: str | None = None,
) -> dict:
    """Create a relationship edge between two nodes."""
    ctx_clause = f" SET context = $context" if context else ""
    result = await db.query(
        f"RELATE {from_id}->{edge_table}->{to_id}{ctx_clause}",
        {"context": context} if context else None,
    )
    return result[0]["result"][0] if result[0]["result"] else {}


async def update_node(db: AsyncSurreal, record_id: str, fields: dict) -> dict:
    """Update fields on an existing node."""
    set_clauses = ", ".join(f"{k} = ${k}" for k in fields)
    result = await db.query(
        f"UPDATE {record_id} SET {set_clauses}, updated_at = time::now()",
        fields,
    )
    return result[0]["result"][0] if result[0]["result"] else {}
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ingest_tools.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add src/second_brain/tools/ingest_tools.py tests/test_ingest_tools.py
git commit -m "feat: ingest agent tools — create notes, entities, edges, updates"
```

---

### Task 6: Recall Agent

**Files:**
- Create: `src/second_brain/agents/recall.py`
- Create: `src/second_brain/agents/__init__.py`
- Create: `tests/test_recall_agent.py`

**Step 1: Write the failing test**

This test uses a mock model to verify the agent is wired correctly — it doesn't make real LLM calls.

```python
# tests/test_recall_agent.py
import pytest
from pydantic_ai.models.test import TestModel

from second_brain.agents.recall import create_recall_agent, RecallDeps
from second_brain.db import init_schema


@pytest.fixture
async def recall_deps(db):
    await init_schema(db)
    # Seed some data
    await db.query("""
        CREATE note:1 SET content = 'Spaced repetition improves memory',
            summary = 'spaced rep', source = 'cli';
        CREATE entity:sr SET name = 'spaced repetition', type = 'concept';
        RELATE note:1->references->entity:sr;
    """)
    return RecallDeps(db=db)


async def test_recall_agent_has_tools():
    agent = create_recall_agent()
    tool_names = {t.name for t in agent._function_tools.values()}
    assert "full_text_search" in tool_names
    assert "get_node" in tool_names
    assert "get_connections" in tool_names
    assert "graph_traverse" in tool_names


async def test_recall_agent_runs(recall_deps):
    agent = create_recall_agent()
    result = await agent.run(
        "What do I know about spaced repetition?",
        deps=recall_deps,
        model=TestModel(),
    )
    assert result.output is not None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_recall_agent.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement recall agent**

```python
# src/second_brain/agents/__init__.py
```

```python
# src/second_brain/agents/recall.py
from dataclasses import dataclass

from pydantic_ai import Agent, RunContext
from surrealdb import AsyncSurreal

from second_brain.config import settings
from second_brain.tools import recall_tools


@dataclass
class RecallDeps:
    db: AsyncSurreal


def create_recall_agent() -> Agent[RecallDeps, str]:
    agent = Agent(
        settings.reasoning_model,
        deps_type=RecallDeps,
        output_type=str,
        system_prompt=(
            "You are a personal knowledge recall agent. The user asks questions and you "
            "explore their knowledge base using the tools available to you. "
            "Use search tools to find relevant notes and entities, follow graph connections "
            "to discover related knowledge, and refine your search based on what you find. "
            "Keep exploring until you have enough context to give a thorough answer. "
            "If you find nothing relevant, say so honestly."
        ),
    )

    @agent.tool
    async def full_text_search(ctx: RunContext[RecallDeps], table: str, query: str) -> list[dict]:
        """Search notes or entities by keyword. Table must be 'note' or 'entity'."""
        return await recall_tools.full_text_search(ctx.deps.db, table, query)

    @agent.tool
    async def vector_search(ctx: RunContext[RecallDeps], table: str, query_embedding: list[float], k: int = 5) -> list[dict]:
        """Find the k nearest notes/entities by semantic similarity."""
        return await recall_tools.vector_search(ctx.deps.db, table, query_embedding, k)

    @agent.tool
    async def get_node(ctx: RunContext[RecallDeps], record_id: str) -> dict:
        """Get a single node by ID, e.g. 'note:abc123' or 'entity:sr'."""
        return await recall_tools.get_node(ctx.deps.db, record_id)

    @agent.tool
    async def get_connections(ctx: RunContext[RecallDeps], record_id: str) -> list[dict]:
        """Get all relationships connected to a node."""
        return await recall_tools.get_connections(ctx.deps.db, record_id)

    @agent.tool
    async def graph_traverse(ctx: RunContext[RecallDeps], record_id: str, depth: int = 2) -> list[dict]:
        """Traverse the knowledge graph from a node up to N hops deep."""
        return await recall_tools.graph_traverse(ctx.deps.db, record_id, depth)

    return agent
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_recall_agent.py -v`
Expected: 2 PASSED

**Step 5: Commit**

```bash
git add src/second_brain/agents/ tests/test_recall_agent.py
git commit -m "feat: recall agent with search and graph traversal tools"
```

---

### Task 7: Ingest Agent

**Files:**
- Create: `src/second_brain/agents/ingest.py`
- Create: `tests/test_ingest_agent.py`

**Step 1: Write the failing test**

```python
# tests/test_ingest_agent.py
import pytest
from unittest.mock import AsyncMock, patch
from pydantic_ai.models.test import TestModel

from second_brain.agents.ingest import create_ingest_agent, IngestDeps
from second_brain.db import init_schema


@pytest.fixture
async def ingest_deps(db):
    await init_schema(db)
    return IngestDeps(db=db, embed_fn=AsyncMock(return_value=[0.1, 0.2, 0.3]))


async def test_ingest_agent_has_tools():
    agent = create_ingest_agent()
    tool_names = {t.name for t in agent._function_tools.values()}
    assert "create_note" in tool_names
    assert "create_entity" in tool_names
    assert "create_edge" in tool_names
    assert "update_node" in tool_names
    assert "search_existing" in tool_names
    assert "embed" in tool_names


async def test_ingest_agent_runs(ingest_deps):
    agent = create_ingest_agent()
    result = await agent.run(
        "I've been thinking about how spaced repetition could help with my coding practice",
        deps=ingest_deps,
        model=TestModel(),
    )
    assert result.output is not None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ingest_agent.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement ingest agent**

```python
# src/second_brain/agents/ingest.py
from dataclasses import dataclass
from typing import Callable, Awaitable

from pydantic_ai import Agent, RunContext
from surrealdb import AsyncSurreal

from second_brain.config import settings
from second_brain.tools import ingest_tools, recall_tools


@dataclass
class IngestDeps:
    db: AsyncSurreal
    embed_fn: Callable[[str], Awaitable[list[float]]]


def create_ingest_agent() -> Agent[IngestDeps, str]:
    agent = Agent(
        settings.reasoning_model,
        deps_type=IngestDeps,
        output_type=str,
        system_prompt=(
            "You are a personal knowledge ingest agent. The user provides raw input — notes, "
            "ideas, rambling thoughts — and you process them into structured knowledge.\n\n"
            "Your job:\n"
            "1. Parse the input into discrete ideas. One note per distinct idea.\n"
            "2. Extract entities (people, projects, concepts, tools) mentioned.\n"
            "3. Search the existing knowledge base to find related entities and notes. "
            "Resolve references like 'that thing I was thinking about' to existing nodes.\n"
            "4. Create notes, entities, and relationship edges. Use the embed tool to generate "
            "vectors for each new note and entity.\n"
            "5. Surface any interesting connections you found to existing knowledge.\n\n"
            "Return a summary of what you stored and any connections you discovered."
        ),
    )

    @agent.tool
    async def create_note(ctx: RunContext[IngestDeps], content: str, source: str = "api", summary: str | None = None) -> dict:
        """Create a new note. Call embed() first to get the embedding vector."""
        return await ingest_tools.create_note(ctx.deps.db, content=content, source=source, summary=summary)

    @agent.tool
    async def create_entity(ctx: RunContext[IngestDeps], name: str, type: str, description: str | None = None) -> dict:
        """Create a new entity (concept, person, project, tool, etc.)."""
        return await ingest_tools.create_entity(ctx.deps.db, name=name, type=type, description=description)

    @agent.tool
    async def create_edge(ctx: RunContext[IngestDeps], from_id: str, edge_table: str, to_id: str, context: str | None = None) -> dict:
        """Create a relationship. edge_table is one of: references, relates_to, derived_from."""
        return await ingest_tools.create_edge(ctx.deps.db, from_id=from_id, edge_table=edge_table, to_id=to_id, context=context)

    @agent.tool
    async def update_node(ctx: RunContext[IngestDeps], record_id: str, fields: dict) -> dict:
        """Update fields on an existing note or entity."""
        return await ingest_tools.update_node(ctx.deps.db, record_id=record_id, fields=fields)

    @agent.tool
    async def search_existing(ctx: RunContext[IngestDeps], table: str, query: str) -> list[dict]:
        """Search existing notes/entities by keyword to find related knowledge."""
        return await recall_tools.full_text_search(ctx.deps.db, table, query)

    @agent.tool
    async def embed(ctx: RunContext[IngestDeps], text: str) -> list[float]:
        """Generate a vector embedding for the given text."""
        return await ctx.deps.embed_fn(text)

    return agent
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ingest_agent.py -v`
Expected: 2 PASSED

**Step 5: Commit**

```bash
git add src/second_brain/agents/ingest.py tests/test_ingest_agent.py
git commit -m "feat: ingest agent with write tools and existing knowledge search"
```

---

### Task 8: FastAPI Application and Endpoints

**Files:**
- Create: `src/second_brain/app.py`
- Create: `tests/test_app.py`

**Step 1: Write the failing tests**

```python
# tests/test_app.py
import pytest
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient

from second_brain.app import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_ingest_endpoint_exists(client):
    # With mocked agent, just verify the endpoint responds
    with patch("second_brain.app.run_ingest_agent", new_callable=AsyncMock) as mock:
        mock.return_value = "Stored 1 note"
        resp = await client.post("/ingest", json={"text": "test note", "source": "cli"})
    assert resp.status_code == 200


async def test_recall_endpoint_exists(client):
    with patch("second_brain.app.run_recall_agent", new_callable=AsyncMock) as mock:
        mock.return_value = "Found nothing relevant"
        resp = await client.post("/recall", json={"question": "what do I know?"})
    assert resp.status_code == 200
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the app**

```python
# src/second_brain/app.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel
from surrealdb import AsyncSurreal

from second_brain.agents.ingest import IngestDeps, create_ingest_agent
from second_brain.agents.recall import RecallDeps, create_recall_agent
from second_brain.config import settings
from second_brain.db import init_schema
from second_brain.embedding import embed_text, init_vector_indexes


_db: AsyncSurreal | None = None
_ingest_agent = create_ingest_agent()
_recall_agent = create_recall_agent()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db
    _db = AsyncSurreal(f"surrealkv://{settings.db_path}")
    await _db.use("brain", "brain")
    await init_schema(_db)
    await init_vector_indexes(_db)
    yield
    if _db:
        await _db.close()
        _db = None


app = FastAPI(title="Second Brain", lifespan=lifespan)


class IngestRequest(BaseModel):
    text: str
    source: str = "api"


class IngestResponse(BaseModel):
    summary: str


class RecallRequest(BaseModel):
    question: str


class RecallResponse(BaseModel):
    answer: str


async def run_ingest_agent(text: str, source: str) -> str:
    result = await _ingest_agent.run(
        f"Source: {source}\n\n{text}",
        deps=IngestDeps(db=_db, embed_fn=embed_text),
    )
    return result.output


async def run_recall_agent(question: str) -> str:
    result = await _recall_agent.run(
        question,
        deps=RecallDeps(db=_db),
    )
    return result.output


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest):
    summary = await run_ingest_agent(req.text, req.source)
    return IngestResponse(summary=summary)


@app.post("/recall", response_model=RecallResponse)
async def recall(req: RecallRequest):
    answer = await run_recall_agent(req.question)
    return RecallResponse(answer=answer)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_app.py -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add src/second_brain/app.py tests/test_app.py
git commit -m "feat: FastAPI app with /ingest, /recall, and /health endpoints"
```

---

### Task 9: Run All Tests and Integration Smoke Test

**Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 2: Fix any failures**

Address any test failures or import issues discovered when running the full suite together.

**Step 3: Manual smoke test**

Create a `.env` file with a real API key, then:

Run: `uv run uvicorn second_brain.app:app --reload`

Test ingest:
```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"text": "I have been thinking about how spaced repetition could improve my coding practice. It reminds me of deliberate practice from the book Peak by Anders Ericsson.", "source": "cli"}'
```

Test recall:
```bash
curl -X POST http://localhost:8000/recall \
  -H "Content-Type: application/json" \
  -d '{"question": "What do I know about learning techniques?"}'
```

**Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: integration test fixes and smoke test verification"
```

---

### Task 10: Final Cleanup and Documentation

**Step 1: Add a README.md**

Minimal README with:
- What this is (one sentence)
- How to install (`uv sync`)
- How to configure (`.env`)
- How to run (`uv run uvicorn second_brain.app:app`)
- API endpoints

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup and usage instructions"
```
