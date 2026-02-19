from surrealdb import AsyncSurreal


async def create_note(
    db: AsyncSurreal,
    content: str,
    source: str,
    summary: str | None = None,
    embedding: list[float] | None = None,
) -> dict:
    """Create a new note in the knowledge base."""
    data: dict = {"content": content, "source": source}
    if summary:
        data["summary"] = summary
    if embedding:
        data["embedding"] = embedding
    result = await db.create("note", data)
    # db.create() returns a single dict in this SDK version
    return result if isinstance(result, dict) else result[0]


async def create_entity(
    db: AsyncSurreal,
    name: str,
    type: str,
    description: str | None = None,
    embedding: list[float] | None = None,
) -> dict:
    """Create a new entity (concept, person, project, etc.)."""
    data: dict = {"name": name, "type": type}
    if description:
        data["description"] = description
    if embedding:
        data["embedding"] = embedding
    result = await db.create("entity", data)
    return result if isinstance(result, dict) else result[0]


async def create_edge(
    db: AsyncSurreal,
    from_id: str,
    edge_table: str,
    to_id: str,
    context: str | None = None,
) -> dict:
    """Create a relationship edge between two nodes."""
    ctx_clause = " SET context = $context" if context else ""
    query = f"RELATE {from_id}->{edge_table}->{to_id}{ctx_clause}"
    result = await db.query(
        query,
        {"context": context} if context else None,
    )
    # db.query() returns a flat list of dicts
    return result[0] if result else {}


async def update_node(db: AsyncSurreal, record_id: str, fields: dict) -> dict:
    """Update fields on an existing node."""
    set_clauses = ", ".join(f"{k} = ${k}" for k in fields)
    result = await db.query(
        f"UPDATE {record_id} SET {set_clauses}, updated_at = time::now()",
        fields,
    )
    # db.query() returns a flat list of dicts
    return result[0] if result else {}
