import logging
from dataclasses import dataclass

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

from second_brain.db import Storage, project_intake_evidence
from second_brain.models import Context, normalize_edge, normalize_node
from second_brain.tools import recall_tools

logger = logging.getLogger(__name__)


class RecallOutput(BaseModel):
    answer: str
    cited_node_ids: list[str] = []
    cited_edge_ids: list[str] = []
    cited_unprocessed_ids: list[str] = []


@dataclass
class RecallDeps:
    storage: Storage


async def fetch_cited_context(storage: Storage, output: RecallOutput) -> Context:
    """Fetch cited graph records and unprocessed intake evidence."""
    node_ids = [
        record_id
        for record_id in output.cited_node_ids
        if record_id.split(":", 1)[0] in {"note", "entity"}
    ]
    fetched_nodes = await storage.get_nodes(node_ids)
    nodes = [normalize_node(node) for node in fetched_nodes]

    edges: list[dict] = []
    for edge_id in output.cited_edge_ids:
        try:
            edge = await storage.get_edge(edge_id)
        except ValueError:
            logger.warning("Recall citations: skipping malformed edge ID %r", edge_id)
            continue
        if edge:
            edges.append(normalize_edge(edge))

    unprocessed: list[dict] = []
    if output.cited_unprocessed_ids:
        chunks = await storage.get_intake_chunks(output.cited_unprocessed_ids)
        for chunk in chunks:
            evidence = project_intake_evidence(chunk)
            evidence["unprocessed"] = True
            evidence.pop("connections", None)
            unprocessed.append(evidence)

    return Context(nodes=nodes, edges=edges, unprocessed=unprocessed)


def create_recall_agent() -> Agent[RecallDeps, RecallOutput]:
    """Create a recall agent with search and graph exploration tools.

    The agent is created without a default model so it can be used in tests
    with TestModel(). In production, pass ``settings.reasoning_model`` to
    ``agent.run(..., model=...)``, or override using
    ``PYDANTIC_AI_MODEL`` env var.
    """
    agent = Agent(
        deps_type=RecallDeps,
        output_type=RecallOutput,
        system_prompt=(
            "You are a personal knowledge recall agent. The user asks questions and you "
            "explore their knowledge base using the tools available to you. "
            "Use search_knowledge to search organized graph memory and explicitly "
            "unprocessed intake evidence by keyword and meaning. Organized results are "
            "graph nodes with edge connections. Unprocessed evidence is raw source text "
            "that has not been organized yet. Use get_node for graph nodes only. "
            "Keep exploring until you have enough context to give a thorough answer. "
            "If you find nothing relevant, say so honestly.\n\n"
            "IMPORTANT: Include every graph node and edge referenced in your answer in "
            "cited_node_ids and cited_edge_ids. Cite raw intake chunks in "
            "cited_unprocessed_ids, never in cited_node_ids."
        ),
    )

    @agent.tool
    async def search_knowledge(
        ctx: RunContext[RecallDeps], query: str, k: int = 5
    ) -> dict:
        """Search organized graph memory and unprocessed intake evidence."""
        logger.info("recall: search_knowledge query='%.80s' k=%d", query, k)
        try:
            result = await recall_tools.search_memory(ctx.deps.storage, query, k)
            logger.info(
                "recall: search_knowledge → %d nodes, %d unprocessed chunks",
                len(result.nodes),
                len(result.unprocessed),
            )
            return {"nodes": result.nodes, "unprocessed": result.unprocessed}
        except Exception as e:
            logger.error("recall: search_knowledge failed: %s", e)
            return {"error": str(e)}

    @agent.tool
    async def get_node(ctx: RunContext[RecallDeps], record_id: str) -> dict:
        """Get a single node by ID, e.g. 'note:abc123' or 'entity:sr'.
        Result includes a 'connections' list showing edges with labels and adjacent node IDs."""
        logger.info("recall: get_node id=%s", record_id)
        try:
            node = await recall_tools.get_node(ctx.deps.storage, record_id)
            if not node:
                return {"error": f"Node {record_id} not found"}
            enriched = await recall_tools.enrich_with_connections(
                ctx.deps.storage, node
            )
            return enriched
        except Exception as e:
            logger.error("recall: get_node failed: %s", e)
            return {"error": str(e)}

    return agent
