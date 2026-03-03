from second_brain.db import init_schema


async def test_init_schema_creates_tables(db):
    await init_schema(db)

    # Verify note table exists by inserting and selecting
    await db.query("CREATE note SET content = 'test', source = 'test'")
    result = await db.query("SELECT * FROM note")
    assert len(result) == 1


async def test_init_schema_creates_entity_table(db):
    await init_schema(db)

    await db.query("CREATE entity SET name = 'Python', type = 'concept'")
    result = await db.query("SELECT * FROM entity")
    assert len(result) == 1


async def test_init_schema_is_idempotent(db):
    await init_schema(db)
    await init_schema(db)  # Should not raise

    await db.query("CREATE note SET content = 'test', source = 'test'")
    result = await db.query("SELECT * FROM note")
    assert len(result) == 1


async def test_dream_age_defaults(db):
    """Nodes and edges get dream_age=0 by default."""
    await init_schema(db)
    await db.query("""
        CREATE note:1 SET content = 'test', source = 'cli';
        CREATE entity:a SET name = 'A', type = 'concept';
        CREATE note:2 SET content = 'test2', source = 'cli';
        RELATE note:1->references->entity:a;
        RELATE entity:a->relates_to->entity:a SET context = 'self';
        RELATE note:1->derived_from->note:2;
    """)
    note = (await db.query("SELECT dream_age FROM note:1"))[0]
    entity = (await db.query("SELECT dream_age FROM entity:a"))[0]
    ref_edges = await db.query("SELECT dream_age FROM references")
    rel_edges = await db.query("SELECT dream_age FROM relates_to")
    der_edges = await db.query("SELECT dream_age FROM derived_from")

    assert note["dream_age"] == 0
    assert entity["dream_age"] == 0
    assert ref_edges[0]["dream_age"] == 0
    assert rel_edges[0]["dream_age"] == 0
    assert der_edges[0]["dream_age"] == 0
