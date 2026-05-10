.PHONY: up down logs build test integration-test shell-api shell-db \
        universe data prices fundamentals factors rank pipeline

# ── Compose lifecycle ─────────────────────────────────────────────────────────────────────────────

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

# ── Database ───────────────────────────────────────────────────────────────────────────────────

shell-db:
	docker compose exec postgres psql -U stocker -d stocker

# ── Service shells ────────────────────────────────────────────────────────────────────────────

shell-api:
	docker compose exec api bash

shell-ingestor:
	docker compose exec av-ingestor bash

shell-factors:
	docker compose exec factor-engine bash

shell-ranker:
	docker compose exec ranker bash

# ── Tests ──────────────────────────────────────────────────────────────────────────────────
# Unit tests: runs without Docker.

test:
	pip install --quiet -e shared pytest pandas numpy pydantic pyyaml
	pytest tests/ -v

# Integration test: spins up Docker Compose with MOCK_DATA=true, runs full pipeline,
# verifies results, then tears down. Requires Docker.
integration-test:
	bash scripts/integration_test.sh

# ── Pipeline steps (run in order) ──────────────────────────────────────────────────────
# Each step polls until the job completes before returning.

universe:
	@echo "Downloading Russell 3000 universe from IWV ETF holdings..."
	@RUN_ID=$$(curl -sf -X POST http://localhost:8001/jobs/fetch-universe \
	           | python3 -c 'import sys,json; print(json.load(sys.stdin)["run_id"])') && \
	echo "  run_id=$$RUN_ID" && \
	until STATUS=$$(curl -sf http://localhost:8001/runs/$$RUN_ID 2>/dev/null \
	                | python3 -c 'import sys,json; print(json.load(sys.stdin).get("status","running"))' 2>/dev/null); \
	      [ "$$STATUS" = "success" ] || [ "$$STATUS" = "failed" ]; do \
		printf '.'; sleep 2; \
	done && echo " $$STATUS"

data:
	@echo "Fetching prices + fundamentals in a single pass..."
	@RUN_ID=$$(curl -sf -X POST http://localhost:8001/jobs/fetch-data \
	           | python3 -c 'import sys,json; print(json.load(sys.stdin)["run_id"])') && \
	echo "  run_id=$$RUN_ID" && \
	until STATUS=$$(curl -sf http://localhost:8001/runs/$$RUN_ID 2>/dev/null \
	                | python3 -c 'import sys,json; print(json.load(sys.stdin).get("status","running"))' 2>/dev/null); \
	      [ "$$STATUS" = "success" ] || [ "$$STATUS" = "failed" ]; do \
		printf '.'; sleep 5; \
	done && echo " $$STATUS"

factors:
	@echo "Calculating factor scores and detecting market regime..."
	@RUN_ID=$$(curl -sf -X POST http://localhost:8002/jobs/calculate \
	           | python3 -c 'import sys,json; print(json.load(sys.stdin)["run_id"])') && \
	echo "  run_id=$$RUN_ID" && \
	until STATUS=$$(curl -sf http://localhost:8002/runs/$$RUN_ID 2>/dev/null \
	                | python3 -c 'import sys,json; print(json.load(sys.stdin).get("status","running"))' 2>/dev/null); \
	      [ "$$STATUS" = "success" ] || [ "$$STATUS" = "failed" ] || [ "$$STATUS" = "skipped" ]; do \
		printf '.'; sleep 3; \
	done && echo " $$STATUS"

rank:
	@echo "Ranking universe by regime-weighted factor scores..."
	@RUN_ID=$$(curl -sf -X POST http://localhost:8003/jobs/rank \
	           | python3 -c 'import sys,json; print(json.load(sys.stdin)["run_id"])') && \
	echo "  run_id=$$RUN_ID" && \
	until STATUS=$$(curl -sf http://localhost:8003/runs/$$RUN_ID 2>/dev/null \
	                | python3 -c 'import sys,json; print(json.load(sys.stdin).get("status","running"))' 2>/dev/null); \
	      [ "$$STATUS" = "success" ] || [ "$$STATUS" = "failed" ] || [ "$$STATUS" = "skipped" ]; do \
		printf '.'; sleep 2; \
	done && echo " $$STATUS"

# Targeted refreshes (use when you only need one dataset updated)
prices:
	@echo "Fetching prices only..."
	curl -sf -X POST http://localhost:8001/jobs/fetch-prices | python3 -m json.tool

fundamentals:
	@echo "Fetching fundamentals only..."
	curl -sf -X POST http://localhost:8001/jobs/fetch-fundamentals | python3 -m json.tool

# Run the full pipeline end-to-end (each step waits for completion before proceeding)
pipeline: universe data factors rank
	@echo ""
	@echo "Pipeline complete. View results:"
	@echo "  Rankings:  http://localhost:8000/rankings"
	@echo "  Regime:    http://localhost:8000/regime"
	@echo "  Universe:  http://localhost:8000/universe"
