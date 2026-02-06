# OpenSearch Alias Hardening & Migration Plan

## Context
The current `OpenSearchClient` implementation lacks safety checks for alias version mismatches and has no explicit promotion mechanism. We need to implement a safe, atomic alias promotion workflow to support zero-downtime upgrades (e.g., changing embedding models or analyzers).

## Technical Implementation Details

### 1. Atomic Alias Swap
We will use the OpenSearch `update_aliases` API to atomically remove the alias from old indices and add it to the new one.

**JSON Structure:**
```json
POST /_aliases
{
  "actions": [
    { "remove": { "index": "old_index_v1", "alias": "heimdex_segments" } },
    { "add": { "index": "new_index_v2", "alias": "heimdex_segments" } }
  ]
}
```

### 2. Code Changes (`client.py`)

#### `get_alias_targets(self) -> list[str]`
Returns the list of physical indices the alias points to.
```python
async def get_alias_targets(self) -> list[str]:
    try:
        exists = await self.client.indices.exists_alias(name=self.alias_name)
        if not exists: return []
        alias_info = await self.client.indices.get_alias(name=self.alias_name)
        return list(alias_info.keys())
    except Exception as e:
        logger.warning("get_alias_targets_failed", error=str(e))
        return []
```

#### `promote_alias_to_current_version(self)`
Performs the atomic swap.
```python
async def promote_alias_to_current_version(self) -> None:
    current_targets = await self.get_alias_targets()
    # Safety: If already correct, skip
    if len(current_targets) == 1 and current_targets[0] == self.index_name:
        return

    actions = []
    for old_index in current_targets:
        actions.append({"remove": {"index": old_index, "alias": self.alias_name}})
    actions.append({"add": {"index": self.index_name, "alias": self.alias_name}})
    
    await self.client.indices.update_aliases(body={"actions": actions})
```

#### `ensure_index_exists(self)` (Modified)
**Current Behavior:** Creates alias if missing.
**New Behavior:** 
- If alias missing -> Create it (point to current version).
- If alias exists -> Check targets.
    - If target != current version -> **WARN ONLY** (Do not auto-fix).
    - This prevents accidental "rollbacks" or "roll-forwards" during mixed-version deployments.

## Execution Phases

### Phase 1: Core Hardening (Blocking)
- **File**: `services/api/app/modules/search/client.py`
- **Tasks**:
    1. Add `get_alias_targets`.
    2. Add `promote_alias_to_current_version`.
    3. Modify `ensure_index_exists` to implement the "Warn-Don't-Touch" safety rule.
    4. Update `get_index_info` to include alias diagnostic data.

### Phase 2: Tools & Verification
- **File**: `services/api/app/modules/search/promote_alias.py`
    - Create a standalone async script (patterned after `seed.py`).
    - Logic: `ensure_index_exists()` -> `promote_alias_to_current_version()` -> Report status.
- **File**: `services/api/tests/test_alias_migration.py`
    - Integration tests using `mock_opensearch_client` or live container.
    - Verify:
        - `ensure_index` does not touch misconfigured aliases.
        - `promote` correctly calls `update_aliases` with remove/add actions.
- **Docs**: Update `README.md` with the new command: `docker compose exec api python -m app.modules.search.promote_alias`.

### Phase 3: Search Quality (Post-Migration)
- **File**: `services/api/tests/test_search_quality.py`
    - Define `GOLDEN_QUERIES` (10 Korean queries).
    - Run searches at `alpha=0` (Keyword), `alpha=0.5` (Hybrid), `alpha=1.0` (Semantic).
    - Assert `Recall@20 > Threshold`.
- **Tuning**: Adjust Nori `user_dictionary` if specific brand terms fail.

## Verification Checklist
- [ ] `ensure_index_exists` logs warning on mismatch.
- [ ] `promote_alias.py` successfully moves alias from vOld -> vNew.
- [ ] Zero downtime observed (atomic operation).
- [ ] Tests pass.
