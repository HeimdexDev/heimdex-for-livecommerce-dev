#!/usr/bin/env bash
# check_no_worker_db_coupling.sh — Guardrail preventing DB coupling in workers.
#
# Workers must be fully DB-free: no SQLAlchemy, no asyncpg, no psycopg2,
# no direct DB sessions, no API source mounts, no DATABASE_URL env vars.
#
# Usage:
#   bash scripts/check_no_worker_db_coupling.sh          # from repo root
#   bash scripts/check_no_worker_db_coupling.sh --ci     # CI mode (same behavior)
#
# Exit codes:
#   0 = clean (no coupling found)
#   1 = violations found
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Worker source directories to scan
WORKER_SRC_DIRS=(
    "services/drive-worker/src"
    "services/drive-caption-worker/src"
    "services/drive-stt-worker/src"
    "services/drive-ocr-worker/src"
    # v0.10: drive-blur-worker joins the scan so the Phase 4 dispatcher
    # + export_layer task cannot silently regress the workers-don't-
    # touch-the-DB contract.
    "services/drive-blur-worker/src"
)

# Worker package manifests (pyproject.toml / Dockerfile)
WORKER_PKG_DIRS=(
    "services/drive-worker"
    "services/drive-caption-worker"
    "services/drive-stt-worker"
    "services/drive-ocr-worker"
    "services/drive-blur-worker"
)

COMPOSE_FILE="docker-compose.yml"

# Worker service names in docker-compose
WORKER_SERVICES=(
    "drive-worker"
    "drive-caption-worker"
    "drive-stt-worker"
    "drive-ocr-worker"
    "drive-blur-worker"
)

violations=0

red()   { printf '\033[0;31m%s\033[0m\n' "$*"; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }

check_pattern() {
    local label="$1"
    local pattern="$2"
    shift 2
    local dirs=("$@")

    for dir in "${dirs[@]}"; do
        local full_path="$REPO_ROOT/$dir"
        if [ ! -d "$full_path" ]; then
            continue
        fi
        local matches
        matches=$(grep -rn --include='*.py' -E "$pattern" "$full_path" 2>/dev/null || true)
        if [ -n "$matches" ]; then
            red "VIOLATION [$label] in $dir:"
            echo "$matches" | head -20
            echo ""
            violations=$((violations + 1))
        fi
    done
}

check_pkg_pattern() {
    local label="$1"
    local pattern="$2"
    shift 2
    local dirs=("$@")

    for dir in "${dirs[@]}"; do
        local full_path="$REPO_ROOT/$dir"
        if [ ! -d "$full_path" ]; then
            continue
        fi
        local matches
        matches=$(grep -rn --include='*.toml' --include='Dockerfile' -E "$pattern" "$full_path" 2>/dev/null || true)
        if [ -n "$matches" ]; then
            red "VIOLATION [$label] in $dir:"
            echo "$matches" | head -10
            echo ""
            violations=$((violations + 1))
        fi
    done
}

# ── Section 1: Worker source code checks ──────────────────────────────

bold "=== Checking worker source code for DB coupling ==="
echo ""

check_pattern "sqlalchemy import" \
    "import sqlalchemy|from sqlalchemy" \
    "${WORKER_SRC_DIRS[@]}"

check_pattern "asyncpg/psycopg2 import" \
    "import asyncpg|import psycopg2|from asyncpg|from psycopg2" \
    "${WORKER_SRC_DIRS[@]}"

check_pattern "DB session/engine" \
    "create_async_engine|async_sessionmaker|AsyncSession|session_factory|SessionLocal" \
    "${WORKER_SRC_DIRS[@]}"

check_pattern "API app imports" \
    "from app\.db|from app\.modules|from app\.config" \
    "${WORKER_SRC_DIRS[@]}"

check_pattern "DATABASE_URL reference" \
    "DATABASE_URL" \
    "${WORKER_SRC_DIRS[@]}"

# ── Section 2: Worker package dependency checks ───────────────────────

bold "=== Checking worker package files for DB dependencies ==="
echo ""

check_pkg_pattern "sqlalchemy dependency" \
    "sqlalchemy" \
    "${WORKER_PKG_DIRS[@]}"

check_pkg_pattern "asyncpg dependency" \
    "asyncpg" \
    "${WORKER_PKG_DIRS[@]}"

check_pkg_pattern "psycopg2 dependency" \
    "psycopg2" \
    "${WORKER_PKG_DIRS[@]}"

# ── Section 3: docker-compose checks ─────────────────────────────────

bold "=== Checking docker-compose.yml for worker DB wiring ==="
echo ""

COMPOSE_PATH="$REPO_ROOT/$COMPOSE_FILE"
if [ -f "$COMPOSE_PATH" ]; then
    for svc in "${WORKER_SERVICES[@]}"; do
        # Extract the service block (from "  <svc>:" to the next service or end)
        # Use awk to grab lines between service definition markers
        svc_block=$(awk "/^  ${svc}:/,/^  [a-z]/" "$COMPOSE_PATH" 2>/dev/null || true)

        if [ -z "$svc_block" ]; then
            continue
        fi

        # Check for DATABASE_URL env vars
        db_url=$(echo "$svc_block" | grep -n "DATABASE_URL" 2>/dev/null || true)
        if [ -n "$db_url" ]; then
            red "VIOLATION [DATABASE_URL in compose] service=$svc:"
            echo "$db_url"
            echo ""
            violations=$((violations + 1))
        fi

        # Check for /opt/heimdex-api mount
        api_mount=$(echo "$svc_block" | grep -n "heimdex-api" 2>/dev/null || true)
        if [ -n "$api_mount" ]; then
            red "VIOLATION [API source mount in compose] service=$svc:"
            echo "$api_mount"
            echo ""
            violations=$((violations + 1))
        fi

        # Check for postgres dependency
        pg_dep=$(echo "$svc_block" | grep -n "postgres" 2>/dev/null || true)
        if [ -n "$pg_dep" ]; then
            red "VIOLATION [postgres dependency in compose] service=$svc:"
            echo "$pg_dep"
            echo ""
            violations=$((violations + 1))
        fi

        # Check for DRIVE_SA_ENCRYPTION_KEY (token broker handles this)
        sa_key=$(echo "$svc_block" | grep -n "DRIVE_SA_ENCRYPTION_KEY" 2>/dev/null || true)
        if [ -n "$sa_key" ]; then
            red "VIOLATION [DRIVE_SA_ENCRYPTION_KEY in compose] service=$svc:"
            echo "$sa_key"
            echo ""
            violations=$((violations + 1))
        fi
    done
else
    echo "Warning: $COMPOSE_FILE not found, skipping compose checks"
fi

# ── Section 4: worker_sdk settings check ──────────────────────────────

bold "=== Checking worker_sdk settings for dead DB fields ==="
echo ""

SDK_SETTINGS="$REPO_ROOT/../heimdex-worker-sdk/src/heimdex_worker_sdk/settings.py"
if [ -f "$SDK_SETTINGS" ]; then
    sdk_db=$(grep -n -E '^\s*(database_url|DATABASE_URL)\b|^\s*(import|from).*(asyncpg|psycopg2)' "$SDK_SETTINGS" 2>/dev/null || true)
    if [ -n "$sdk_db" ]; then
        red "VIOLATION [DB fields in worker_sdk settings]:"
        echo "$sdk_db"
        echo ""
        violations=$((violations + 1))
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────

echo ""
if [ "$violations" -gt 0 ]; then
    red "============================================"
    red "  FAILED: $violations violation(s) found"
    red "============================================"
    echo ""
    echo "Workers must be fully DB-free (Phase 1 policy)."
    echo "See docs/coupling_audit/ for architecture context."
    exit 1
else
    green "============================================"
    green "  PASSED: No worker DB coupling detected"
    green "============================================"
    exit 0
fi
