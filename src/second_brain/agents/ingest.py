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
    """Create an ingest agent with bulk write tools and knowledge search.

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
            "2. Extract entities (people, projects, organizations, places, events, concepts, "
            "technologies) mentioned.\n"
            "3. **Deduplicate entities**: Before creating any entity, search the existing "
            "knowledge base first. Do ONE broad search covering the main topic of the input "
            "rather than searching for each entity individually — this is much faster. "
            "If a matching entity already exists (same name or clearly the "
            "same concept), DO NOT create a duplicate — use the existing entity's ID when creating "
            "edges. Only create a new entity when it is genuinely absent from the knowledge base.\n"
            "4. Create notes, entities, and edges. Build a rich relationship graph:\n"
            "   - **Entity→entity edges are the most valuable.** Always create direct relationships "
            "between entities: person→designed→artifact, mission→part_of→program, "
            "person→recruited_via→operation, launch_vehicle→launched→mission, etc.\n"
            "   - Connect notes to the primary entities they describe using 'describes' edges.\n"
            "   - Create hierarchical edges: missions belong to programs (part_of), "
            "sub-projects belong to parent projects, people belong to organizations (member_of).\n"
            "   - Choose descriptive, semantically meaningful edge names. The edge name should "
            "read naturally and convey specific meaning.\n"
            "   Good: designed_by, led, part_of, member_of, launched_from, launched, "
            "recruited_via, triggered, caused, preceded, succeeded, crewed_by, built_by, located_in\n"
            "   Bad: references, relates_to, linked_to, associated_with, about, mentions\n"
            "   Embeddings are generated automatically when you create notes and entities.\n"
            "5. Surface any interesting connections you found to existing knowledge.\n\n"
            "Return a summary of what you stored and any connections you discovered."
        ),
    )

    @agent.tool
    async def search_knowledge(
        ctx: RunContext[IngestDeps], tables: list[str], query: str, k: int = 5
    ) -> list[dict]:
        """Search existing notes/entities using hybrid keyword + semantic search.
        tables: list containing 'note', 'entity', or both.
        Results include a 'connections' list showing edges with labels and adjacent node IDs."""
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
            enriched = []
            for r in all_results:
                e = await recall_tools.enrich_with_connections(ctx.deps.db, r)
                enriched.append(make_serializable(e))
            logger.info("ingest: search_knowledge → %d results", len(enriched))
            return enriched
        except Exception as e:
            logger.error("ingest: search_knowledge failed: %s", e)
            return [{"error": str(e)}]

    @agent.tool
    async def get_node(ctx: RunContext[IngestDeps], record_id: str) -> dict:
        """Get a single node by ID, e.g. 'note:abc123' or 'entity:sr'.
        Result includes a 'connections' list showing edges with labels and adjacent node IDs."""
        logger.info("ingest: get_node id=%s", record_id)
        try:
            node = await recall_tools.get_node(ctx.deps.db, record_id)
            if not node:
                return {"error": f"Node {record_id} not found"}
            enriched = await recall_tools.enrich_with_connections(ctx.deps.db, node)
            return make_serializable(enriched)
        except Exception as e:
            logger.error("ingest: get_node failed: %s", e)
            return {"error": str(e)}

    @agent.tool
    async def create_notes(
        ctx: RunContext[IngestDeps],
        notes: list[dict],
    ) -> list[dict]:
        """Create multiple notes in bulk. Each dict needs 'content', optional 'source' (default 'api') and 'summary'.
        Embeddings are generated automatically."""
        logger.info("ingest: create_notes (%d notes)", len(notes))
        try:
            results = await ingest_tools.create_notes(
                ctx.deps.db, notes, ctx.deps.embed_fn
            )
            return [make_serializable(r) for r in results]
        except Exception as e:
            logger.error("ingest: create_notes failed: %s", e)
            return [{"error": str(e)}]

    @agent.tool
    async def create_entities(
        ctx: RunContext[IngestDeps],
        entities: list[dict],
    ) -> list[dict]:
        """Create multiple entities in bulk. Each dict needs 'name', 'type', optional 'description'.
        Embeddings are generated automatically."""
        logger.info("ingest: create_entities (%d entities)", len(entities))
        try:
            results = await ingest_tools.create_entities(
                ctx.deps.db, entities, ctx.deps.embed_fn
            )
            return [make_serializable(r) for r in results]
        except Exception as e:
            logger.error("ingest: create_entities failed: %s", e)
            return [{"error": str(e)}]

    @agent.tool
    async def create_edges(
        ctx: RunContext[IngestDeps],
        edges: list[dict],
    ) -> list[dict]:
        """Create multiple relationship edges in bulk. Each dict needs 'from_id', 'edge_table', 'to_id', optional 'context'.
        edge_table should be a descriptive, semantically meaningful name (e.g. authored_by, inspired_by, depends_on, part_of, builds_upon)."""
        logger.info("ingest: create_edges (%d edges)", len(edges))
        try:
            results = await ingest_tools.create_edges(ctx.deps.db, edges)
            return [make_serializable(r) for r in results]
        except Exception as e:
            logger.error("ingest: create_edges failed: %s", e)
            return [{"error": str(e)}]

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

    return agent
