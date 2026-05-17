"""Phase 3 import-surface guard: forbid direct calls to the scene
pipeline primitives from worker task modules.

After Phase 3 both ``drive-worker/src/tasks/process.py`` and
``drive-transcode-worker/src/tasks/transcode.py`` must go through the
shared ``heimdex_media_pipelines.scenes.scene_pipeline.build_scene_documents``
helper. Inlining detect → keyframes → assemble was the Phase-3-target
duplication; re-inlining silently drifts the two paths out of sync.

Exempt: ``drive-worker/src/tasks/resplit.py`` — users provide custom
per-request thresholds that intentionally bypass the cache / shared
helper. The exemption is codified here so removing it requires a
deliberate edit (not an accidental re-introduction).

This is a **static text scan**, not an AST analysis. The worker code
uses ``importlib.import_module(...).symbol`` for lazy imports, so an
AST-level import-graph check wouldn't catch anything. Matching the
function names as attribute access / word-boundary text is the most
reliable gate.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


# Forbidden function names when called from a pipeline worker.
_FORBIDDEN_SYMBOLS = (
    "detect_scenes",
    "extract_all_keyframes",
    "assemble_scenes",
    "boundaries_from_cuts",
)

# Patterns that must NOT appear in the scanned files. Covers both static
# imports (`from X import Y`, `import Y`) and dynamic `importlib` access.
_FORBIDDEN_PATTERNS = (
    [re.compile(rf"\b{sym}\s*\(") for sym in _FORBIDDEN_SYMBOLS]                  # direct call
    + [re.compile(rf"\.{sym}\b") for sym in _FORBIDDEN_SYMBOLS]                   # attribute access (importlib lazy)
    + [re.compile(rf"\bimport\s+{sym}\b") for sym in _FORBIDDEN_SYMBOLS]          # `import Y`
)


# Files in scope for the Phase-3 guard.
_SCOPED_FILES = [
    Path(__file__).parent.parent.parent / "drive-transcode-worker" / "src" / "tasks" / "transcode.py",
    Path(__file__).parent.parent.parent / "drive-worker" / "src" / "tasks" / "process.py",
]

# Files explicitly exempted. See docstring.
_EXEMPT_FILES = {
    "resplit.py",
    "scene_split.py",  # pending migration in Phase 4; exempt until that phase lands.
}


@pytest.mark.parametrize("source_path", _SCOPED_FILES, ids=lambda p: p.name)
def test_worker_source_does_not_call_scene_primitives_directly(source_path: Path) -> None:
    assert source_path.is_file(), (
        f"expected worker source at {source_path} — update "
        f"_SCOPED_FILES if the file moved"
    )
    if source_path.name in _EXEMPT_FILES:
        pytest.skip(f"{source_path.name} is exempt from the import-surface guard")
    text = source_path.read_text()
    offenders: list[tuple[str, int, str]] = []
    for pattern in _FORBIDDEN_PATTERNS:
        for match in pattern.finditer(text):
            # Locate the line for reporting.
            line_no = text[:match.start()].count("\n") + 1
            line = text.splitlines()[line_no - 1].strip()
            offenders.append((pattern.pattern, line_no, line))
    if offenders:
        msg_lines = [
            f"{source_path.name} calls a forbidden scene primitive directly.",
            "After Phase 3, use heimdex_media_pipelines.scenes.scene_pipeline."
            "build_scene_documents() instead.",
            "Offending occurrences:",
        ]
        for pattern, line_no, line in offenders:
            msg_lines.append(f"  L{line_no}: {line}  (matched /{pattern}/)")
        pytest.fail("\n".join(msg_lines))


def test_exempt_files_are_still_allowed_to_use_primitives() -> None:
    """Sanity-check: resplit.py DOES import these symbols (that's the
    whole point of the exemption). If it stops doing so, the exemption
    is stale and should be removed from ``_EXEMPT_FILES``.
    """
    resplit = (Path(__file__).parent.parent.parent
               / "drive-worker" / "src" / "tasks" / "resplit.py")
    assert resplit.is_file()
    text = resplit.read_text()
    # resplit.py is permitted to call these; we just check it's still
    # using them so the exemption doesn't rot into a no-op.
    assert any(sym in text for sym in _FORBIDDEN_SYMBOLS), (
        "resplit.py no longer uses any scene primitive directly — "
        "remove it from the _EXEMPT_FILES allowlist."
    )
