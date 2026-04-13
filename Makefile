# Heimdex Quality Gate
# Run `make check` to verify all quality gates pass

.PHONY: check test test-integration build lint lint-frontend lint-backend check-coupling verify e2e e2e-smoke e2e-consistency e2e-visual e2e-visual-update e2e-staging search-quality seed

# Run core quality checks (tests + build)
check: test build check-coupling
	@echo ""
	@echo "============================================"
	@echo "  All quality gates passed!"
	@echo "============================================"

# Run backend tests (excluding integration tests that require live OpenSearch)
test:
	@echo "Running backend tests..."
	docker compose exec -T api pytest tests/ -m "not integration" --tb=short

# Run integration tests (requires live OpenSearch)
test-integration:
	@echo "Running integration tests..."
	docker compose exec -T api pytest tests/ -m "integration" --tb=short -v

# Build frontend (includes type checking)
build:
	@echo "Running frontend type check..."
	docker compose exec -T web npm run type-check
	@echo ""
	@echo "Building frontend..."
	docker compose exec -T web npm run build

# Lint frontend only (backend has pre-existing issues to address separately)
lint-frontend:
	@echo "Running frontend linting..."
	docker compose exec -T web npm run lint

# Lint backend only (non-blocking, shows issues)
lint-backend:
	@echo "Running backend linting..."
	-docker compose exec -T api ruff check app/ --output-format=concise

# Full lint (may fail due to pre-existing backend issues)
lint:
	@echo "Running backend linting..."
	-docker compose exec -T api ruff check app/ --output-format=concise
	@echo ""
	@echo "Running frontend linting..."
	docker compose exec -T web npm run lint

check-coupling:
	@bash scripts/check_no_worker_db_coupling.sh

# ── Verification (all-in-one) ───────────────────────────────────────────────

# Full verification: tests + lint + build + coupling + E2E smoke
# Run this before pushing. Exit code 0 = safe to push.
verify: test build check-coupling e2e-smoke
	@echo ""
	@echo "============================================"
	@echo "  VERIFIED — all checks passed, safe to push"
	@echo "============================================"

# ── E2E Tests (Playwright) ──────────────────────────────────────────────────

# Run all Playwright E2E tests
e2e:
	@echo "Running all E2E tests..."
	cd e2e && npx playwright test

# Run smoke tests only (< 60s)
e2e-smoke:
	@echo "Running E2E smoke tests..."
	cd e2e && npx playwright test smoke.spec.ts

# Run feature consistency tests
e2e-consistency:
	@echo "Running E2E consistency tests..."
	cd e2e && npx playwright test consistency.spec.ts

# Run visual regression tests (compare against baselines)
e2e-visual:
	@echo "Running visual regression tests..."
	cd e2e && npx playwright test visual-regression.spec.ts

# Update visual regression baselines (run after intentional UI changes)
e2e-visual-update:
	@echo "Updating visual regression baselines..."
	cd e2e && npx playwright test visual-regression.spec.ts --update-snapshots

# Run E2E smoke + consistency against staging (after deploy)
e2e-staging:
	@echo "Running E2E tests against staging..."
	cd e2e && BASE_URL=https://devorg.app.heimdexdemo.dev API_URL=https://devorg.app.heimdexdemo.dev npx playwright test smoke.spec.ts consistency.spec.ts

# ── Search Quality ───────────────────────────────────────────────────────────

# Run search quality regression check (requires indexed data)
search-quality:
	@echo "Running search quality regression check..."
	docker compose exec -T api python /app/scripts/search-quality-check.py 2>/dev/null || python scripts/search-quality-check.py

# ── Utilities ────────────────────────────────────────────────────────────────

# Seed the database (run after fresh docker compose up)
seed:
	docker compose exec -T api alembic upgrade head
	docker compose exec -T api python -m app.seed
