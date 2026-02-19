from surrealdb import AsyncSurreal

from second_brain.config import settings


async def get_db() -> AsyncSurreal:  # pyright: ignore[reportGeneralTypeIssues]
    """Create and return an embedded SurrealDB connection."""
    db = AsyncSurreal(f"surrealkv://{settings.db_path}")  # pyright: ignore[reportGeneralTypeIssues]
    await db.use("brain", "brain")
    await init_schema(db)
    return db


async def init_schema(db: AsyncSurreal) -> None:  # pyright: ignore[reportGeneralTypeIssues]
    """Define tables, fields, and indexes. Idempotent."""
    await db.query("""
        -- Full-text search analyzer
        DEFINE ANALYZER IF NOT EXISTS simple_analyzer
            TOKENIZERS blank, class, camel, punct
            FILTERS lowercase, snowball(english);

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
            SEARCH ANALYZER simple_analyzer BM25;
        DEFINE INDEX IF NOT EXISTS entity_name_fts ON entity FIELDS name
            SEARCH ANALYZER simple_analyzer BM25;
    """)
