.PHONY: up down logs build build-base test integration-test migrate-fresh-test init shell-api shell-db shell-pipeline \
        universe data prices fundamentals run-pipeline vet portfolio pipeline pull-model deploy

# ── Compose lifecycle ──────────────────────────────────────────────────────────────────────────────────────────────────────────

init:
	@mkdir -p artifacts
	@echo "Directories ready."

up: init
	docker compose up -d

down:
	docker compose down

build-base:
	docker build --network host -t stocker-base:latest -f Dockerfile.base .

build: build-base
	docker compose build

# NAS deploy: mirrors one-click-applied config into git, rebases, pushes, then
# rebuilds SERVICES. Example: make deploy SERVICES="api pipeline"
deploy:
	./scripts/deploy.sh $(SERVICES)

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

shell-pipeline:
	docker compose exec pipeline bash

# ── Tests ──────────────────────────────────────────────────────────────────────────────────────────────────
# Unit tests: runs without Docker.

test:
	pip install --quiet -e shared pytest pandas numpy pydantic pyyaml hypothesis
	pytest tests/ -v

# Integration test: spins up Docker Compose with MOCK_DATA=true, runs full pipeline,
# verifies results, then tears down. Requires Docker.
integration-test:
	bash scripts/integration_test.sh

# Verify migrations work from a completely blank postgres (no existing schema).
# Run this after every new migration file before pushing.
# Requires Docker.  Tears down the test volume on exit.
migrate-fresh-test:
	@echo "=== Fresh-install migration test ==="
	@docker volume rm stocker_pgdata_migrate_test 2>/dev/null || true
	@docker run -d --name stocker_pg_migrate_test \
	    -e POSTGRES_USER=stocker \
	    -e POSTGRES_PASSWORD=stocker \
	    -e POSTGRES_DB=stocker \
	    -v stocker_pgdata_migrate_test:/var/lib/postgresql/data \
	    postgres:16 >/dev/null
	@echo "Waiting for postgres to be ready..."
	@until docker exec stocker_pg_migrate_test pg_isready -U stocker -h 127.0.0.1 -q; do sleep 1; done
	@sleep 2
	@echo "Running all migrations from scratch..."
	@docker run --rm \
	    --network container:stocker_pg_migrate_test \
	    -e DATABASE_URL=postgresql://stocker:stocker@127.0.0.1:5432/stocker \
	    $(shell docker build -q -f services/db-migrator/Dockerfile .) \
	    /app/migrate.sh && \
	    echo "=== Migration test PASSED ===" || \
	    (echo "=== Migration test FAILED ===" && \
	     docker stop stocker_pg_migrate_test >/dev/null && \
	     docker rm stocker_pg_migrate_test >/dev/null && \
	     docker volume rm stocker_pgdata_migrate_test >/dev/null || true && \
	     exit 1)
	@docker stop stocker_pg_migrate_test >/dev/null
	@docker rm stocker_pg_migrate_test >/dev/null
	@docker volume rm stocker_pgdata_migrate_test >/dev/null || true

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

run-pipeline:
	@echo "Running factors → rank → delta (unified pipeline service)..."
	$(call poll_job,http://localhost:8018/jobs/run,http://localhost:8018,3,skipped)

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

# ── LLM vetter ────────────────────────────────────────────────────────────────

# Pull the Ollama model (run once after first `make up`; downloads ~9 GB)
pull-model:
	@echo "Pulling $(OLLAMA_MODEL) into Ollama (this may take several minutes)..."
	docker compose exec ollama ollama pull $(or $(OLLAMA_MODEL),qwen2.5:7b)
	@echo "Model ready."

# Run LLM vetter on the latest ranking run, show results, and prompt for approval.
# Usage: make vet
# To skip and go straight to portfolio: make portfolio
vet:
	@echo "Running LLM vetter (model: $(or $(OLLAMA_MODEL),qwen2.5:7b))..."
	$(eval VET_RUN_ID := $(shell curl -sf -X POST http://localhost:8016/jobs/vet | python3 -c "import sys,json; print(json.load(sys.stdin)['run_id'])"))
	@echo "Vetter run started: $(VET_RUN_ID)"
	@echo "Polling for completion..."
	@until [ "$$(curl -sf http://localhost:8016/runs/$(VET_RUN_ID) | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")" != "running" ]; do \
		printf "."; sleep 5; \
	done
	@echo ""
	@echo "=== LLM Vetter Results ==="
	@curl -sf http://localhost:8016/runs/$(VET_RUN_ID)/exclusions | python3 -c "\
import sys, json; \
d = json.load(sys.stdin); \
excs = d['exclusions']; \
print(f\"Flagged {len(excs)} tickers for exclusion:\"); \
[print(f\"  [{e['confidence'].upper():6}] {e['ticker']}: {e['reason'][:80]}\") for e in excs] or print('  (none flagged)'); \
"
	@echo ""
	@read -p "Approve these exclusions? [y/N] " ans; \
	if [ "$$ans" = "y" ] || [ "$$ans" = "Y" ]; then \
		curl -sf -X POST http://localhost:8016/runs/$(VET_RUN_ID)/approve > /dev/null; \
		echo "Approved. Run: make portfolio VETTER_RUN_ID=$(VET_RUN_ID)"; \
	else \
		echo "Not approved. Run: make portfolio  (to build without vetter exclusions)"; \
	fi

# Run the full pipeline end-to-end (each step waits for completion before proceeding)
pipeline: universe data run-pipeline portfolio
	@echo ""
	@echo "Pipeline complete. View results:"
	@echo "  Rankings:  http://localhost:8000/rankings"
	@echo "  Regime:    http://localhost:8000/regime"
	@echo "  Universe:  http://localhost:8000/universe"
