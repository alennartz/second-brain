import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic_ai import Agent, RunContext
from surrealdb import AsyncSurreal

from second_brain.models import make_serializable
from second_brain.tools import ingest_tools, recall_tools

logger = logging.getLogger(__name__)


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
            "4. Create notes, entities, and relationship edges. Embeddings are generated "
            "automatically when you create notes and entities.\n"
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
        """Create a new note. Embedding is generated automatically."""
        logger.info("ingest: create_note (%d chars) source=%s", len(content), source)
        try:
            embedding = await ctx.deps.embed_fn(content)
            result = await ingest_tools.create_note(
                ctx.deps.db,
                content=content,
                source=source,
                summary=summary,
                embedding=embedding,
            )
            serialized = make_serializable(result)
            logger.info("ingest: create_note → id=%s", serialized.get("id"))
            return serialized
        except Exception as e:
            logger.error("ingest: create_note failed: %s", e)
            return {"error": str(e)}

    @agent.tool
    async def create_entity(
        ctx: RunContext[IngestDeps],
        name: str,
        type: str,
        description: str | None = None,
    ) -> dict:
        """Create a new entity (concept, person, project, tool, etc.). Embedding is generated automatically."""
        logger.info("ingest: create_entity name='%s' type=%s", name, type)
        try:
            text_to_embed = description or name
            embedding = await ctx.deps.embed_fn(text_to_embed)
            result = await ingest_tools.create_entity(
                ctx.deps.db,
                name=name,
                type=type,
                description=description,
                embedding=embedding,
            )
            serialized = make_serializable(result)
            logger.info("ingest: create_entity → id=%s", serialized.get("id"))
            return serialized
        except Exception as e:
            logger.error("ingest: create_entity failed: %s", e)
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
        logger.info("ingest: create_edge %s -[%s]-> %s", from_id, edge_table, to_id)
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
            logger.error("ingest: create_edge failed: %s", e)
            return {"error": str(e)}

    @agent.tool
    async def update_node(
        ctx: RunContext[IngestDeps], record_id: str, fields: dict
    ) -> dict:
        """Update fields on an existing note or entity."""
        logger.info(
            "ingest: update_node id=%s fields=%s", record_id, list(fields.keys())
        )
        try:
            result = await ingest_tools.update_node(
                ctx.deps.db, record_id=record_id, fields=fields
            )
            return make_serializable(result)
        except Exception as e:
            logger.error("ingest: update_node failed: %s", e)
            return {"error": str(e)}

    @agent.tool
    async def search_knowledge(
        ctx: RunContext[IngestDeps], tables: list[str], query: str, k: int = 5
    ) -> list[dict]:
        """Search existing notes/entities using hybrid keyword + semantic search.
        tables: list containing 'note', 'entity', or both."""
        logger.info(
            "ingest: search_knowledge tables=%s query='%.80s' k=%d", tables, query, k
        )
        try:
            query_embedding = await ctx.deps.embed_fn(query)
            all_results: list[dict] = []
            for table in tables:
                results = await recall_tools.hybrid_search(
                    ctx.deps.db, table, query, query_embedding, k
                )
                all_results.extend(results)
            logger.info("ingest: search_knowledge → %d results", len(all_results))
            return all_results
        except Exception as e:
            logger.error("ingest: search_knowledge failed: %s", e)
            return [{"error": str(e)}]

    return agent
