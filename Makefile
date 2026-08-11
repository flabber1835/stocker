.PHONY: help test lint sentinel-up sentinel-down status panel check-data \
        feed-seed feed-daily feed-status feed-repair identity certify \
        base-image sentinel-image

# ── Sentinel ────────────────────────────────────────────────────────────────
#
# This file used to carry `up`, `deploy`, `pipeline`, `vet`, `pull-model` and a
# shell into every one of sixteen Stocker services. Those services were deleted
# in ac0c71f, and the import-closure analysis that justified the deletion proved
# only that SENTINEL could not reach them. It said nothing about whether the
# repository still TOLD PEOPLE to run them — and it did, in the file an operator
# opens first, as executable commands rather than comments.
#
# There is one production architecture. Nothing here may name a retired one.
# Recover it from `stocker-legacy-2026-08` if you need to read it.

# THE RESOLVER, not a hardcoded -f. A host without CPU CFS quota (Synology
# DSM, kernel 3.10) makes the daemon REFUSE any container declaring `cpus:`, so
# the compose file that can actually run there is generated. `:=` so the probe
# happens once per make invocation rather than per reference.
COMPOSE  := docker compose $(shell bash scripts/sentinel-compose.sh)
GIT_SHA  := $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)

help:
	@echo "Sentinel"
	@echo "  make test           every suite, each in its own process"
	@echo "  make status         ownership binding, feed frontier, readiness"
	@echo "  make panel          start the read-only panel on :8004"
	@echo "  make sentinel-up    panel + database (never the CLI)"
	@echo "  make sentinel-down  stop them (NEVER with volumes)"
	@echo ""
	@echo "  make feed-seed      full Sharadar history. Hours"
	@echo "  make feed-daily     fetch from the stored frontier"
	@echo "  make feed-status    ingest progress, readable MID-RUN"
	@echo "  make feed-repair    split ratios that contradict ACTIONS"
	@echo "  make check-data     the Wealth Core data contract, per CHECK"
	@echo ""
	@echo "  make identity       what this environment and corpus ARE"
	@echo "  make certify        the in-image certification suite"
	@echo "  make sentinel-image build sentinel:$(GIT_SHA)"
	@echo ""
	@echo "  migrate-account and adopt-restored-account are DELIBERATELY absent."
	@echo "  They change account ownership and are run by hand, read first."

# ── tests ───────────────────────────────────────────────────────────────────
#
# The install line is the CONTRACT for a green run: a suite whose dependency is
# missing ERRORS at collection, which reads as a broken repository rather than
# an unprovisioned runner. `aiosqlite` earned its place that way.
#
# Process-per-suite is not a preference. Every service package is named `app`,
# so a single cross-suite process is order-dependent; see scripts/run-tests.sh.
test:
	pip install --quiet -e shared pytest pandas numpy pydantic pyyaml hypothesis \
	    sqlalchemy aiosqlite httpx exchange_calendars psycopg
	bash scripts/run-tests.sh

lint:
	python -m pyflakes sentinel/ tests/sentinel/

# ── images ──────────────────────────────────────────────────────────────────
#
# TAGGED BY COMMIT as well as `latest`. The Python base is pinned by digest,
# Postgres is pinned by digest and the dependency closure is locked — and then
# the application image was only `sentinel:latest`, so a running container could
# not say which commit it was.
#
# The compose file keeps the literal `latest` alias deliberately: interpolating
# a tag there would trip scripts/compose_image.py, which refuses `${...}`
# because it cannot know the environment Compose ran with. Pinning is verified
# through the identity record's image DIGEST instead — stronger than a tag,
# since a tag can be moved.
base-image:
	docker build --network host -t stocker-base:latest -f Dockerfile.base .

sentinel-image:
	docker build --network host \
	    -t sentinel:$(GIT_SHA) -t sentinel:latest -f Dockerfile.sentinel .
	@echo "built sentinel:$(GIT_SHA)"

# ── running ─────────────────────────────────────────────────────────────────
#
# `sentinel-up` starts the DATABASE and the read-only PANEL. It does not start
# the CLI, which lives behind the `cli` profile precisely so that
# `docker compose up` can never begin an account handover.
sentinel-up:
	$(COMPOSE) up -d sentinel-postgres sentinel-panel

# NEVER `--volumes`. It deletes the behavioural state and the corpus, and the
# behavioural state is the half that is not rebuildable from a vendor.
sentinel-down:
	$(COMPOSE) down

panel: sentinel-up
	@echo "panel: http://localhost:8004"

# ── operator reads ──────────────────────────────────────────────────────────
status:
	$(COMPOSE) run --rm sentinel status

check-data:
	$(COMPOSE) run --rm sentinel check-data

identity:
	$(COMPOSE) run --rm sentinel identity

feed-status:
	$(COMPOSE) run --rm sentinel feed-status

# ── feed ────────────────────────────────────────────────────────────────────
feed-seed:
	$(COMPOSE) run --rm sentinel feed-seed

feed-daily:
	$(COMPOSE) run --rm sentinel feed-daily

# DRY by default; this is the one command permitted to lower a split ratio.
feed-repair:
	@test -n "$(START)" -a -n "$(END)" || \
	    { echo "usage: make feed-repair START=YYYY-MM-DD END=YYYY-MM-DD [APPLY=1]"; exit 2; }
	$(COMPOSE) run --rm sentinel feed-repair \
	    --start $(START) --end $(END) $(if $(APPLY),--apply,)

# ── certification ───────────────────────────────────────────────────────────
certify:
	bash scripts/sentinel-certify.sh
