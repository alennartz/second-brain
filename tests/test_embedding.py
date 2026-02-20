from second_brain.db import init_schema, init_vector_indexes


async def test_init_vector_indexes(db):
    await init_schema(db)
    await init_vector_indexes(db, dimensions=3)

    # Should not raise on second call
    await init_vector_indexes(db, dimensions=3)
