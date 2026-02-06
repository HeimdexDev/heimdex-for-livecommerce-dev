"""
Promote OpenSearch alias to current index version.

Usage:
    python -m app.modules.search.promote_alias

This command performs an atomic alias swap to point the search alias
to the current versioned index. It is safe to run multiple times -
if the alias already points to the current index, no changes are made.

Migration Workflow:
    1. Bump INDEX_VERSION in client.py
    2. Deploy new code
    3. Run `python -m app.seed` to populate new index
    4. Run `python -m app.modules.search.promote_alias` to swap alias
    5. Verify search works correctly
    6. (Optional) Delete old index later
"""
import asyncio
import sys

from app.logging_config import get_logger
from app.modules.search.client import OpenSearchClient

logger = get_logger(__name__)


async def main() -> int:
    """
    Main entry point for alias promotion CLI.
    
    Returns:
        0 on success, 1 on error.
    """
    print("=" * 60)
    print("OpenSearch Alias Promotion Tool")
    print("=" * 60)
    print()
    
    client = OpenSearchClient()
    
    try:
        # Step 1: Ensure index exists (creates if missing, warns on mismatch)
        print(f"Target index: {client.index_name}")
        print(f"Target alias: {client.alias_name}")
        print()
        
        print("Step 1: Checking index state...")
        ensure_result = await client.ensure_index_exists()
        
        if ensure_result.get("index_created"):
            print(f"  - Created new index: {client.index_name}")
        else:
            print(f"  - Index already exists: {client.index_name}")
        
        if ensure_result.get("alias_created"):
            print(f"  - Created alias: {client.alias_name} -> {client.index_name}")
            print()
            print("SUCCESS: Index and alias created. No promotion needed.")
            return 0
        
        if ensure_result.get("alias_mismatch_warning"):
            print(f"  - WARNING: {ensure_result['alias_mismatch_warning']}")
        
        # Step 2: Get current diagnostics
        print()
        print("Step 2: Getting current alias state...")
        info = await client.get_index_info()
        
        print(f"  - Alias: {info.get('alias_name')}")
        print(f"  - Intended index: {info.get('intended_index')}")
        print(f"  - Index version: {info.get('index_version')}")
        print(f"  - Index exists: {info.get('index_exists')}")
        print(f"  - Alias exists: {info.get('alias_exists')}")
        print(f"  - Current alias targets: {info.get('alias_targets')}")
        print(f"  - Alias points to current: {info.get('alias_points_to_current')}")
        print(f"  - Alias mismatch: {info.get('alias_mismatch')}")
        print(f"  - Document count: {info.get('document_count')}")
        print(f"  - Embedding dimension: {info.get('embedding_dimension')}")
        
        if info.get("alias_points_to_current"):
            print()
            print("SUCCESS: Alias already points to current index. No changes needed.")
            return 0
        
        if not info.get("index_exists"):
            print()
            print("ERROR: Target index does not exist. Run seeding first.")
            return 1
        
        # Step 3: Promote alias
        print()
        print("Step 3: Promoting alias to current version...")
        print(f"  - Swapping alias from {info.get('alias_targets')} to [{client.index_name}]")
        
        result = await client.promote_alias_to_current_version()
        
        if result.get("already_current"):
            print("  - Alias was already current (no-op)")
        else:
            print(f"  - Before: {result.get('before_targets')}")
            print(f"  - After: {result.get('after_targets')}")
        
        # Step 4: Verify
        print()
        print("Step 4: Verifying promotion...")
        final_info = await client.get_index_info()
        
        print(f"  - Alias targets: {final_info.get('alias_targets')}")
        print(f"  - Points to current: {final_info.get('alias_points_to_current')}")
        print(f"  - Document count: {final_info.get('document_count')}")
        
        if final_info.get("alias_points_to_current"):
            print()
            print("=" * 60)
            print("SUCCESS: Alias promotion completed successfully!")
            print("=" * 60)
            return 0
        else:
            print()
            print("ERROR: Alias verification failed after promotion.")
            return 1
            
    except Exception as e:
        logger.error("promote_alias_failed", error=str(e))
        print()
        print(f"ERROR: {e}")
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
