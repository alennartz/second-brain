export const schema = `
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
        DEFINE FIELD IF NOT EXISTS dream_age ON note TYPE int DEFAULT 0;

        -- Entity table
        DEFINE TABLE IF NOT EXISTS entity SCHEMALESS;
        DEFINE FIELD IF NOT EXISTS name ON entity TYPE string;
        DEFINE FIELD IF NOT EXISTS type ON entity TYPE string;
        DEFINE FIELD IF NOT EXISTS description ON entity TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS embedding ON entity TYPE option<array<float>>;
        DEFINE FIELD IF NOT EXISTS dream_age ON entity TYPE int DEFAULT 0;

        -- Edge tables
        DEFINE TABLE IF NOT EXISTS references SCHEMALESS;
        DEFINE FIELD IF NOT EXISTS dream_age ON references TYPE int DEFAULT 0;
        DEFINE TABLE IF NOT EXISTS relates_to SCHEMALESS;
        DEFINE FIELD IF NOT EXISTS context ON relates_to TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS dream_age ON relates_to TYPE int DEFAULT 0;
        DEFINE TABLE IF NOT EXISTS derived_from SCHEMALESS;
        DEFINE FIELD IF NOT EXISTS dream_age ON derived_from TYPE int DEFAULT 0;

        -- Full-text indexes
        DEFINE INDEX IF NOT EXISTS note_content_fts ON note FIELDS content
            SEARCH ANALYZER simple_analyzer BM25;
        DEFINE INDEX IF NOT EXISTS entity_name_fts ON entity FIELDS name
            SEARCH ANALYZER simple_analyzer BM25;

        -- Synchronous intake queue
        DEFINE TABLE IF NOT EXISTS intake_chunk SCHEMALESS;
        DEFINE FIELD IF NOT EXISTS intake_id ON intake_chunk TYPE string;
        DEFINE FIELD IF NOT EXISTS chunk_index ON intake_chunk TYPE int;
        DEFINE FIELD IF NOT EXISTS total_chunks ON intake_chunk TYPE int;
        DEFINE FIELD IF NOT EXISTS content ON intake_chunk TYPE string;
        DEFINE FIELD IF NOT EXISTS source ON intake_chunk TYPE string;
        DEFINE FIELD IF NOT EXISTS hints ON intake_chunk TYPE array<string>;
        DEFINE FIELD IF NOT EXISTS embedding ON intake_chunk TYPE option<array<float>>;
        DEFINE FIELD IF NOT EXISTS state ON intake_chunk TYPE string;
        DEFINE FIELD IF NOT EXISTS attempt_count ON intake_chunk TYPE int DEFAULT 0;
        DEFINE FIELD IF NOT EXISTS next_attempt_at ON intake_chunk TYPE option<datetime>;
        DEFINE FIELD IF NOT EXISTS lease_token ON intake_chunk TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS lease_expires_at ON intake_chunk TYPE option<datetime>;
        DEFINE FIELD IF NOT EXISTS worker_id ON intake_chunk TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS last_error ON intake_chunk TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS idempotency_key ON intake_chunk TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS paused ON intake_chunk TYPE bool DEFAULT false;
        DEFINE FIELD IF NOT EXISTS created_at ON intake_chunk TYPE datetime;
        DEFINE FIELD IF NOT EXISTS updated_at ON intake_chunk TYPE datetime;
        DEFINE INDEX IF NOT EXISTS intake_chunk_content_fts ON intake_chunk FIELDS content
            SEARCH ANALYZER simple_analyzer BM25;
        DEFINE INDEX IF NOT EXISTS intake_chunk_intake_id ON intake_chunk FIELDS intake_id;
        DEFINE INDEX IF NOT EXISTS intake_chunk_state ON intake_chunk FIELDS state;

        DEFINE TABLE IF NOT EXISTS intake_key SCHEMALESS;
        DEFINE FIELD IF NOT EXISTS intake_id ON intake_key TYPE string;
        DEFINE FIELD IF NOT EXISTS fingerprint ON intake_key TYPE option<string>;
        DEFINE FIELD IF NOT EXISTS chunk_count ON intake_key TYPE option<int>;
    `;
export function vectorSchema(dimensions: number): string {
 return ["note", "entity", "intake_chunk"].map(table => `DEFINE INDEX IF NOT EXISTS ${table}_embedding_hnsw ON ${table} FIELDS embedding HNSW DIMENSION ${dimensions} DIST COSINE;`).join("\n");
}
