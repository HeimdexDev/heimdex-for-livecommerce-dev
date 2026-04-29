"""Pytest configuration for product-enumerate-worker tests.

Adds the worker's ``src/`` to sys.path so tests can do
``from src.tasks.enumerate import ...`` without installing the
package — matches the pattern used by drive-blur-worker.
"""

from __future__ import annotations

import sys
from pathlib import Path

_worker_root = Path(__file__).resolve().parent.parent
if str(_worker_root) not in sys.path:
    sys.path.insert(0, str(_worker_root))
