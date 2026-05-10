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
	@curl -sf -X POST http://localhost:8001/jobs/fetch-universe | python3 -m json.tool
	@echo "Waiting for universe snapshot..."
	@until [ "$$(curl -sf http://localhost:8001/status | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["universe_tickers"])' 2>/dev/null)" -gt "0" ] 2>/dev/null; do \
		printf '.'; sleep 2; \
	done
	@echo " done."

data:
	@echo "Fetching prices + fundamentals in a single pass..."
	@curl -sf -X POST http://localhost:8001/jobs/fetch-data | python3 -m json.tool
	@echo "Waiting for price data..."
	@until [ "$$(curl -sf http://localhost:8001/status | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["price_rows"])' 2>/dev/null)" -gt "0" ] 2>/dev/null; do \
		printf '.'; sleep 3; \
	done
	@echo " done."

factors:
	@echo "Calculating factor scores and detecting market regime..."
	@curl -sf -X POST http://localhost:8002/jobs/calculate | python3 -m json.tool
	@echo "Waiting for factor run to complete..."
	@until curl -sf http://localhost:8002/regime/current | python3 -c 'import sys,json; d=json.load(sys.stdin); exit(0 if d.get("regime") else 1)' 2>/dev/null; do \
		printf '.'; sleep 3; \
	done
	@echo " done."

rank:
	@echo "Ranking universe by regime-weighted factor scores..."
	@curl -sf -X POST http://localhost:8003/jobs/rank | python3 -m json.tool
	@echo "Waiting for rankings..."
	@until curl -sf http://localhost:8000/rankings?limit=1 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); exit(0 if d.get("count",0)>0 else 1)' 2>/dev/null; do \
		printf '.'; sleep 2; \
	done
	@echo " done."

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
