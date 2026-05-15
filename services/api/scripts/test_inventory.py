#!/usr/bin/env python3
"""Report API test files, pytest markers, and CI allowlist coverage.

This script is intentionally stdlib-only so it can run before the API dev
environment is fully installed. It is a planning aid for the test-suite
refactor; it does not replace pytest collection.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
TESTS_ROOT = API_ROOT / "tests"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"
CORE_MANIFEST = TESTS_ROOT / "core_test_files.txt"

LANE_MARKERS = {
    "core",
    "contract",
    "integration",
    "quality",
    "external",
    "slow",
    "legacy",
    "deprecated",
}


def _rel(path: Path) -> str:
    return path.relative_to(API_ROOT).as_posix()


def _test_files() -> list[Path]:
    return sorted(TESTS_ROOT.glob("test_*.py"))


def _extract_workflow_allowlist() -> set[str]:
    if not WORKFLOW.exists():
        return set()
    paths: set[str] = set()
    for line in WORKFLOW.read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        paths.update(
            match.group(1)
            for match in re.finditer(r"\b(tests/test_[A-Za-z0-9_]+\.py)\b", line)
        )
    return paths


def _read_manifest(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _marker_names_from_expr(expr: ast.AST) -> set[str]:
    names: set[str] = set()
    if isinstance(expr, ast.Attribute):
        if isinstance(expr.value, ast.Attribute) and expr.value.attr == "mark":
            names.add(expr.attr)
    elif isinstance(expr, ast.Call):
        names.update(_marker_names_from_expr(expr.func))
    elif isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        for elt in expr.elts:
            names.update(_marker_names_from_expr(elt))
    return names


def _file_markers(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return set()

    markers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in node.decorator_list:
                markers.update(_marker_names_from_expr(decorator))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "pytestmark":
                    markers.update(_marker_names_from_expr(node.value))
    return markers & LANE_MARKERS


def main() -> int:
    files = _test_files()
    allowlist = _extract_workflow_allowlist()
    core_manifest = _read_manifest(CORE_MANIFEST)
    marker_by_file = {_rel(path): _file_markers(path) for path in files}

    effective_marker_by_file = {
        path: markers | ({"core"} if path in core_manifest else set())
        for path, markers in marker_by_file.items()
    }
    marked = {path for path, markers in effective_marker_by_file.items() if markers}
    unmarked = sorted(set(marker_by_file) - marked)
    allowlisted = sorted(set(marker_by_file) & allowlist)
    allowlisted_unmarked = [path for path in allowlisted if not effective_marker_by_file[path]]
    missing_from_tree = sorted(allowlist - set(marker_by_file))
    manifest_missing_from_tree = sorted(core_manifest - set(marker_by_file))
    workflow_only = sorted(allowlist - core_manifest)
    manifest_only = sorted(core_manifest - allowlist)

    marker_counts: Counter[str] = Counter()
    for markers in effective_marker_by_file.values():
        marker_counts.update(markers)

    print("API test inventory")
    print(f"  files: {len(files)}")
    print(f"  allowlisted in .github/workflows/test.yml: {len(allowlisted)}")
    print(f"  files in tests/core_test_files.txt: {len(core_manifest)}")
    print(f"  files with lane markers: {len(marked)}")
    print(f"  files without lane markers: {len(unmarked)}")
    print()

    if marker_counts:
        print("Marker counts")
        for marker, count in sorted(marker_counts.items()):
            print(f"  {marker}: {count}")
        print()

    if missing_from_tree:
        print("Allowlist entries missing from tests/")
        for path in missing_from_tree:
            print(f"  {path}")
        print()

    if manifest_missing_from_tree:
        print("Core manifest entries missing from tests/")
        for path in manifest_missing_from_tree:
            print(f"  {path}")
        print()

    if workflow_only:
        print("Workflow allowlist entries missing from core manifest")
        for path in workflow_only:
            print(f"  {path}")
        print()

    if manifest_only:
        print("Core manifest additions beyond workflow allowlist")
        for path in manifest_only:
            print(f"  {path}")
        print()

    print("Allowlisted files without lane markers")
    for path in allowlisted_unmarked:
        print(f"  {path}")
    print()

    print("Unmarked files")
    for path in unmarked:
        print(f"  {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
