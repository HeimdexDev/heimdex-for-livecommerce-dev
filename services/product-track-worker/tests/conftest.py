"""Test fixtures for the product-track-worker scaffold."""

import sys
from pathlib import Path

# Make ``src.*`` imports resolve in tests without installing the
# worker as a package (mirrors product-enumerate-worker's conftest).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
