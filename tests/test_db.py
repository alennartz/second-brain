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
