# Documentation Updates

## 1. README.md

Add this section under "Development" > "Database Migrations":

### Search Index Migration

The search service uses **zero-downtime index migration** via aliasing.
- **Read Alias**: `heimdex_segments` (used by API)
- **Write Index**: `heimdex_segments_v2` (current version)

**To upgrade the index (e.g., after changing embedding model):**

1. Update `INDEX_VERSION` in `services/api/app/modules/search/client.py`.
2. Deploy the code. The new index will be created automatically, but the **alias will NOT move** (safety check).
3. Run the promotion script to atomically swap the alias:

```bash
docker compose exec api python -m app.modules.search.promote_alias
```

4. If successful, the API will immediately start serving results from the new index.

## 2. docs/architecture.md

Update the "Search Index (OpenSearch)" section or add a new "Index Versioning" section:

### Index Versioning & Zero-Downtime Migration

Heimdex uses an alias-based strategy to allow atomic upgrades of the search index structure (mappings, analyzers, or embedding dimensions) without downtime.

**Structure:**
- **Alias** (`heimdex_segments`): The stable name used by the application for all read/write operations.
- **Indices** (`heimdex_segments_v1`, `heimdex_segments_v2`, ...): The physical indices containing data.

**Migration Workflow:**
1. **Creation**: When the application starts, it checks for `INDEX_VERSION` (defined in code). If the corresponding physical index doesn't exist, it is created.
2. **Safety**: If the alias already points to an older version (e.g., `v1`), the application **logs a warning** but continues to function using the old index. It does **not** automatically switch the alias to prevent accidental data loss or schema mismatches during rolling deployments.
3. **Promotion**: An administrator must explicitly run the promotion tool (`promote_alias.py`). This tool performs an **atomic alias swap**:
   ```json
   POST /_aliases
   {
     "actions": [
       { "remove": { "index": "heimdex_segments_v1", "alias": "heimdex_segments" } },
       { "add":    { "index": "heimdex_segments_v2", "alias": "heimdex_segments" } }
     ]
   }
   ```
   This ensures that no requests fail during the transition.
