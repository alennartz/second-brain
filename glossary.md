# Second Brain Glossary

Second Brain stores, retrieves, and refines knowledge for humans and agents.

## Language

**Intake document**:
A logical source submission represented by an ordered set of document chunks while ingestion processes it.
_Avoid_: queue item, ingest job, unprocessed document

**Document chunk**:
An ordered segment of an intake document, stored and indexed for hybrid search until processed.
_Avoid_: staging chunk, unprocessed note

**Processing batch**:
The contiguous document chunks packed into one ingest-agent call.
_Avoid_: ingestion increment, chunk batch

## Relationships

- An **intake document** produces one or more **document chunks**.
- A **document chunk** belongs to exactly one **intake document**.
- A **processing batch** contains one or more **document chunks**.
