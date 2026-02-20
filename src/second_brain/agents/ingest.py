from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic_ai import Agent, RunContext
from surrealdb import AsyncSurreal

from second_brain.models import make_serializable
from second_brain.tools import ingest_tools


@dataclass
class IngestDeps:
    db: AsyncSurreal  # pyright: ignore[reportGeneralTypeIssues] - SDK types AsyncSurreal as function
    embed_fn: Callable[[str], Awaitable[list[float]]]


def create_ingest_agent() -> Agent[IngestDeps, str]:
    """Create an ingest agent with write tools and existing knowledge search.

    The agent is created without a default model so it can be used in tests
    with TestModel(). In production, pass ``settings.reasoning_model`` to
    ``agent.run(..., model=...)``, or override using
    ``PYDANTIC_AI_MODEL`` env var.
    """
    agent = Agent(
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
    async def create_note(
        ctx: RunContext[IngestDeps],
        content: str,
        source: str = "api",
        summary: str | None = None,
    ) -> dict:
        """Create a new note. Call embed() first to get the embedding vector."""
        try:
            result = await ingest_tools.create_note(
                ctx.deps.db, content=content, source=source, summary=summary
            )
            return make_serializable(result)
        except Exception as e:
            return {"error": str(e)}

    @agent.tool
    async def create_entity(
        ctx: RunContext[IngestDeps],
        name: str,
        type: str,
        description: str | None = None,
    ) -> dict:
        """Create a new entity (concept, person, project, tool, etc.)."""
        try:
            result = await ingest_tools.create_entity(
                ctx.deps.db, name=name, type=type, description=description
            )
            return make_serializable(result)
        except Exception as e:
            return {"error": str(e)}

    @agent.tool
    async def create_edge(
        ctx: RunContext[IngestDeps],
        from_id: str,
        edge_table: str,
        to_id: str,
        context: str | None = None,
    ) -> dict:
        """Create a relationship. edge_table is one of: references, relates_to, derived_from."""
        try:
            result = await ingest_tools.create_edge(
                ctx.deps.db,
                from_id=from_id,
                edge_table=edge_table,
                to_id=to_id,
                context=context,
            )
            return make_serializable(result)
        except Exception as e:
            return {"error": str(e)}

    @agent.tool
    async def update_node(
        ctx: RunContext[IngestDeps], record_id: str, fields: dict
    ) -> dict:
        """Update fields on an existing note or entity."""
        try:
            result = await ingest_tools.update_node(
                ctx.deps.db, record_id=record_id, fields=fields
            )
            return make_serializable(result)
        except Exception as e:
            return {"error": str(e)}

    @agent.tool
    async def search_existing(
        ctx: RunContext[IngestDeps], table: str, query: str
    ) -> list[dict]:
        """Search existing notes/entities by keyword to find related knowledge."""
        field = "content" if table == "note" else "name"
        return await ctx.deps.db.query(
            f"SELECT *, search::score(1) AS score FROM {table} "
            f"WHERE {field} @1@ $query ORDER BY score DESC LIMIT 10",
            {"query": query},
        )

    @agent.tool
    async def embed(ctx: RunContext[IngestDeps], text: str) -> list[float]:
        """Generate a vector embedding for the given text."""
        return await ctx.deps.embed_fn(text)

    return agent
