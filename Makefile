.PHONY: up down logs build test integration-test shell-api shell-db \
        universe data prices fundamentals factors rank portfolio pipeline

# ── Compose lifecycle ──────────────────────────────────────────────────────────────────────────────────────────────────────────

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

# ── Database ──────────────────────────────────────────────────────────────────────────────────────────────

shell-db:
	docker compose exec postgres psql -U stocker -d stocker

# ── Service shells ────────────────────────────────────────────────────────────────────────────────────────────

shell-api:
	docker compose exec api bash

shell-ingestor:
	docker compose exec av-ingestor bash

shell-factors:
	docker compose exec factor-engine bash

shell-ranker:
	docker compose exec ranker bash

# ── Tests ──────────────────────────────────────────────────────────────────────────────────────────────────
# Unit tests: runs without Docker.

test:
	pip install --quiet -e shared pytest pandas numpy pydantic pyyaml
	pytest tests/ -v

# Integration test: spins up Docker Compose with MOCK_DATA=true, runs full pipeline,
# verifies results, then tears down. Requires Docker.
integration-test:
	bash scripts/integration_test.sh

# ── Pipeline helpers ───────────────────────────────────────────────────────────────────────────────────────
# $(1)=POST URL  $(2)=runs base URL  $(3)=sleep secs  $(4)=extra terminal status (optional)
define poll_job
	@RUN_ID=$$(curl -sf -X POST $(1) \
	           | python3 -c 'import sys,json; print(json.load(sys.stdin)["run_id"])') && \
	echo "  run_id=$$RUN_ID" && \
	until STATUS=$$(curl -sf $(2)/runs/$$RUN_ID 2>/dev/null \
	                | python3 -c 'import sys,json; print(json.load(sys.stdin).get("status","running"))' 2>/dev/null); \
	      [ "$$STATUS" = "success" ] || [ "$$STATUS" = "failed" ]$(if $(4), || [ "$$STATUS" = "$(4)" ]); do \
		printf '.'; sleep $(3); \
	done && echo " $$STATUS"
endef

# ── Pipeline steps (run in order) ──────────────────────────────────────────────────────────────────────────────
# Each step polls until the job completes before returning.

universe:
	@echo "Downloading Russell 3000 universe from IWV ETF holdings..."
	$(call poll_job,http://localhost:8001/jobs/fetch-universe,http://localhost:8001,2)

data:
	@echo "Fetching prices + fundamentals in a single pass..."
	$(call poll_job,http://localhost:8001/jobs/fetch-data,http://localhost:8001,5,partial_success)

factors:
	@echo "Calculating factor scores and detecting market regime..."
	$(call poll_job,http://localhost:8002/jobs/calculate,http://localhost:8002,3,skipped)

rank:
	@echo "Ranking universe by regime-weighted factor scores..."
	$(call poll_job,http://localhost:8003/jobs/rank,http://localhost:8003,2,skipped)

# Targeted refreshes (use when you only need one dataset updated)
prices:
	@echo "Fetching prices only..."
	$(call poll_job,http://localhost:8001/jobs/fetch-prices,http://localhost:8001,5,partial_success)

fundamentals:
	@echo "Fetching fundamentals only..."
	$(call poll_job,http://localhost:8001/jobs/fetch-fundamentals,http://localhost:8001,5,partial_success)

portfolio:
	@echo "Building greedy covariance-penalized portfolio from latest ranking run..."
	$(call poll_job,http://localhost:8008/jobs/build,http://localhost:8008,2)

# Run the full pipeline end-to-end (each step waits for completion before proceeding)
pipeline: universe data factors rank portfolio
	@echo ""
	@echo "Pipeline complete. View results:"
	@echo "  Rankings:  http://localhost:8000/rankings"
	@echo "  Regime:    http://localhost:8000/regime"
	@echo "  Universe:  http://localhost:8000/universe"
