# Migration Scripts

One-shot scripts for migrating data from legacy storage to PostgreSQL multi-tenant schema.

## Order

1. `migrate_airtable_to_bookings.py <org_id>`
2. `migrate_chromadb_to_pgvector.py <org_id>`

## Prerequisites

- PostgreSQL with multi-tenant schema applied (see `src/core/db/schema.sql`)
- Environment variables:
  - `POSTGRES_DSN` -- PostgreSQL connection string
  - `AIRTABLE_API_KEY` (for bookings migration)
  - `AIRTABLE_BASE_ID` (for bookings migration)
- ChromaDB data directory at `data/chroma/` (for documents migration)

## Verification

After each migration, verify row counts match:

```sql
SELECT COUNT(*) FROM bookings;
SELECT COUNT(*) FROM documents;
SELECT COUNT(*) FROM document_chunks;
```
