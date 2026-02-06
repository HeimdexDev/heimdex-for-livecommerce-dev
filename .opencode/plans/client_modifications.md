# Client.py Modification Spec

This file contains the exact code changes required for `services/api/app/modules/search/client.py`.

## 1. Add Helper Methods

Add these methods to the `OpenSearchClient` class (e.g., before `ensure_index_exists`):

```python
    async def get_alias_targets(self) -> list[str]:
        """
        Get list of indices the alias currently points to.
        Returns empty list if alias does not exist.
        """
        try:
            exists = await self.client.indices.exists_alias(name=self.alias_name)
            if not exists:
                return []
            
            alias_info = await self.client.indices.get_alias(name=self.alias_name)
            return list(alias_info.keys())
        except Exception as e:
            logger.warning("get_alias_targets_failed", error=str(e))
            return []

    async def promote_alias_to_current_version(self) -> None:
        """
        Atomically swap the alias to point ONLY to the current versioned index.
        """
        try:
            current_targets = await self.get_alias_targets()
            
            # If alias already points ONLY to current index, do nothing
            if len(current_targets) == 1 and current_targets[0] == self.index_name:
                logger.info("alias_promotion_skipped", reason="already_up_to_date", index=self.index_name)
                return

            actions = []
            
            # Remove alias from old targets
            for old_index in current_targets:
                actions.append({
                    "remove": {
                        "index": old_index,
                        "alias": self.alias_name
                    }
                })
            
            # Add alias to new target
            actions.append({
                "add": {
                    "index": self.index_name,
                    "alias": self.alias_name
                }
            })
            
            if actions:
                await self.client.indices.update_aliases(body={"actions": actions})
                logger.info(
                    "alias_promoted", 
                    alias=self.alias_name, 
                    previous_targets=current_targets, 
                    new_target=self.index_name
                )
        except Exception as e:
            logger.error("alias_promotion_failed", error=str(e))
            raise
```

## 2. Update `ensure_index_exists`

Replace the existing method with:

```python
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def ensure_index_exists(self) -> None:
        """
        Ensure the index exists. 
        
        Alias Behavior:
        - If alias missing: Create it pointing to current index.
        - If alias exists but points elsewhere: WARN ONLY (do not auto-fix).
          This allows zero-downtime migrations via manual promotion.
        """
        # 1. Ensure Index Exists
        index_exists = await self.client.indices.exists(index=self.index_name)
        if not index_exists:
            await self.create_index()
        
        # 2. Handle Alias Safety
        alias_exists = await self.client.indices.exists_alias(name=self.alias_name)
        
        if not alias_exists:
            # Safe to create
            await self.client.indices.put_alias(
                index=self.index_name,
                name=self.alias_name,
            )
            logger.info("created_alias", alias=self.alias_name, index=self.index_name)
        else:
            # Check for Mismatch
            targets = await self.get_alias_targets()
            if self.index_name not in targets:
                # CRITICAL: Do not auto-fix. Just warn.
                logger.warning(
                    "alias_mismatch_detected",
                    alias=self.alias_name,
                    expected=self.index_name,
                    actual_targets=targets,
                    help="Run promote_alias CLI to fix this safely."
                )
            elif len(targets) > 1:
                logger.warning(
                    "alias_multiple_targets_detected",
                    alias=self.alias_name,
                    targets=targets,
                    help="Run promote_alias CLI to clean up old targets."
                )
```

## 3. Update `create_index`

Remove the `aliases` block from the body.

**Old:**
```python
                    "aliases": {
                        self.alias_name: {}  # Create alias pointing to this index
                    },
```

**New:** (Just remove it)

## 4. Update `get_index_info`

Update the return dictionary to include targets:

```python
    async def get_index_info(self) -> dict[str, Any]:
        # ... existing code ...
        try:
            # Get alias info
            # CHANGE: Use helper
            indices_with_alias = await self.get_alias_targets()
            
            # ... existing code ...
            
            return {
                "alias_name": self.alias_name,
                "current_index": self.index_name,
                "indices_with_alias": indices_with_alias,
                "alias_correct": (len(indices_with_alias) == 1 and indices_with_alias[0] == self.index_name),
                # ... rest ...
            }
```
