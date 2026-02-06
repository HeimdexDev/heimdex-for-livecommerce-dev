.PHONY: lint format type-check test test-unit test-integration all

lint:
	ruff check app/ tests/

format:
	ruff format app/ tests/

type-check:
	mypy app/

test:
	pytest tests/

test-unit:
	pytest tests/ -m "not integration"

test-integration:
	pytest tests/ -m "integration"

all: lint type-check test
