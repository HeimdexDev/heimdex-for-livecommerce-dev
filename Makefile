# Heimdex Quality Gate
# Run `make check` to verify all quality gates pass

.PHONY: check test test-integration build lint lint-frontend lint-backend

# Run core quality checks (tests + build)
check: test build
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
