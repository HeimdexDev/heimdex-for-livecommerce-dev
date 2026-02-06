# Implementation Details

## 1. CLI Script: `services/api/app/modules/search/promote_alias.py`

```python
import asyncio
import sys
from typing import NoReturn

from app.logging_config import setup_logging, get_logger
from app.modules.search.client import OpenSearchClient

setup_logging()
logger = get_logger(__name__)

async def main() -> None:
    logger.info("starting_alias_promotion_tool")
    
    client = OpenSearchClient()
    
    try:
        # 1. Ensure the V2 index exists (but don't touch alias yet)
        logger.info("verifying_index_exists", index=client.index_name)
        await client.ensure_index_exists()
        
        # 2. Check current state
        targets = await client.get_alias_targets()
        logger.info("current_alias_targets", targets=targets)
        
        if not targets:
            logger.info("no_alias_found_creating_new", alias=client.alias_name)
            # ensure_index_exists should have created it if missing, 
            # but if it was deleted in between, ensure_index creates it.
            # We can force promotion just in case.
        
        if len(targets) == 1 and targets[0] == client.index_name:
            logger.info("alias_already_up_to_date", index=client.index_name)
            return

        # 3. Promote
        logger.info("promoting_alias", from_targets=targets, to_index=client.index_name)
        await client.promote_alias_to_current_version()
        
        # 4. Verify
        new_targets = await client.get_alias_targets()
        logger.info("promotion_complete_verification", current_targets=new_targets)
        
        if len(new_targets) == 1 and new_targets[0] == client.index_name:
            logger.info("SUCCESS_alias_updated")
        else:
            logger.error("FAILURE_alias_mismatch_after_promotion", targets=new_targets)
            sys.exit(1)

    except Exception as e:
        logger.exception("promotion_failed_unexpected_error", error=str(e))
        sys.exit(1)
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
```

## 2. Integration Tests: `services/api/tests/test_alias_migration.py`

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.modules.search.client import OpenSearchClient

@pytest.fixture
def mock_opensearch():
    with patch("app.modules.search.client.AsyncOpenSearch") as mock:
        client = mock.return_value
        client.indices.exists = AsyncMock(return_value=True)
        client.indices.exists_alias = AsyncMock(return_value=True)
        client.indices.get_alias = AsyncMock()
        client.indices.update_aliases = AsyncMock()
        client.close = AsyncMock()
        yield client

@pytest.mark.asyncio
async def test_ensure_index_warns_on_mismatch_and_does_not_fix(mock_opensearch):
    """
    If alias points to 'v1' but code expects 'v2', ensure_index_exists
    should warn and NOT update the alias automatically.
    """
    # Setup
    client = OpenSearchClient()
    # Mock that index v2 exists
    mock_opensearch.indices.exists.return_value = True
    # Mock that alias exists
    mock_opensearch.indices.exists_alias.return_value = True
    # Mock that alias points to OLD version
    mock_opensearch.indices.get_alias.return_value = {"heimdex_segments_v1": {}}
    
    # Execute
    await client.ensure_index_exists()
    
    # Verify
    # Should check alias targets
    mock_opensearch.indices.get_alias.assert_called_with(name=client.alias_name)
    # Should NOT call put_alias (that would be the auto-fix)
    mock_opensearch.indices.put_alias.assert_not_called()

@pytest.mark.asyncio
async def test_promote_alias_atomic_swap(mock_opensearch):
    """
    promote_alias_to_current_version should atomically remove old targets and add new one.
    """
    client = OpenSearchClient()
    # Alias currently points to v1 and some_other_index
    mock_opensearch.indices.get_alias.return_value = {
        "heimdex_segments_v1": {},
        "heimdex_segments_legacy": {}
    }
    
    await client.promote_alias_to_current_version()
    
    # Verify update_aliases call structure
    mock_opensearch.indices.update_aliases.assert_called_once()
    call_args = mock_opensearch.indices.update_aliases.call_args
    body = call_args.kwargs['body']
    actions = body['actions']
    
    # Expect 3 actions: remove v1, remove legacy, add v2
    assert len(actions) == 3
    
    # Verify adds/removes
    removes = [a['remove']['index'] for a in actions if 'remove' in a]
    adds = [a['add']['index'] for a in actions if 'add' in a]
    
    assert "heimdex_segments_v1" in removes
    assert "heimdex_segments_legacy" in removes
    assert client.index_name in adds # v2
```
