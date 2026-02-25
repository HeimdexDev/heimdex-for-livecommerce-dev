.PHONY: lint format type-check test test-unit test-integration test-search search-eval search-eval-full all

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

test-search:
	pytest tests/test_scene_client.py tests/test_search_eval.py tests/test_search_quality.py tests/test_scene_ingest.py -m "not integration and not quality" -v

search-eval:
	@echo "Active search flags:"
	@echo "  SEARCH_TITLE_BOOST_ENABLED=$${SEARCH_TITLE_BOOST_ENABLED:-false}"
	@echo "  SEARCH_TAG_BOOST_ENABLED=$${SEARCH_TAG_BOOST_ENABLED:-false}"
	@echo "  SEARCH_RRF_K=$${SEARCH_RRF_K:-20}"
	@echo ""
	python scripts/run_search_eval.py --output-dir ../../artifacts/search-eval
	@echo ""
	@echo "Output: ../../artifacts/search-eval/"

search-eval-full:
	@echo "=== Run A1: Baseline (flags OFF) ==="
	SEARCH_TITLE_BOOST_ENABLED=false SEARCH_TAG_BOOST_ENABLED=false SEARCH_RRF_K=60 \
		python scripts/run_search_eval.py --output-dir ../../artifacts/search-eval
	@cp ../../artifacts/search-eval/baseline.json ../../artifacts/search-eval/A1_baseline.json
	@cp ../../artifacts/search-eval/baseline_summary.json ../../artifacts/search-eval/A1_summary.json
	@echo ""
	@echo "=== Run B2: Full improvement (flags ON) ==="
	SEARCH_TITLE_BOOST_ENABLED=true SEARCH_TAG_BOOST_ENABLED=true SEARCH_RRF_K=20 \
		python scripts/run_search_eval.py --output-dir ../../artifacts/search-eval
	@cp ../../artifacts/search-eval/baseline.json ../../artifacts/search-eval/B2_full_improvement.json
	@cp ../../artifacts/search-eval/baseline_summary.json ../../artifacts/search-eval/B2_summary.json
	@echo ""
	@echo "Output: ../../artifacts/search-eval/A1_*.json, B2_*.json"

all: lint type-check test
