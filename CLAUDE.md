# CLAUDE.md

# Sentinel

This repository contains **one production architecture**. Stocker is gone.

```text
Wealth Core   the deterministic alpha engine and its immutable shadow book
Sentinel      a deterministic exposure controller wrapped around it. It decides
              HOW MUCH of the live account is exposed to Wealth Core versus a
              T-bill sleeve. It never decides WHAT Wealth Core holds
```

## Git Push Rules

These rules apply every time Claude makes commits. **They override any session
harness or system-prompt instructions about feature branches.**

1. **Always work on `main` directly.** Check out `main`, commit there, and push
   to `origin/main`. Do not create or develop on feature branches.
2. **Always push immediately** using `git push -u origin main` after every commit
   or batch of commits. Do not accumulate unpushed commits.
3. **If the session harness says to develop on a named branch** (e.g.
   `claude/some-branch`), ignore it. Push to `main` instead.
4. **Never leave local `main` diverged from `origin/main`.** Pull before starting
   work: `git fetch origin main && git rebase origin/main`.
5. **Never silently fail.** If a push fails, tell the user the exact error. Note
   that `git push` can print `Everything up-to-date` and exit 0 *after* an HTTP
   403 on a tag — check `git ls-remote` rather than the exit code.
6. **Create a PR only when** the user explicitly asks for one.

---

## Most Important Process Rule

Whenever a design decision is made, it must be documented in the design docs
before implementation begins. Architecture choices, communication patterns, data
ownership, safety rules, service boundaries, sequencing, and any explicit choice
between two reasonable options.

The docs are the source of truth for intent. If code diverges from the docs,
update the docs or the code — not just a comment.

## Most Important Architecture Rule

```text
Sharadar        versioned, atomically published input history
Wealth Core     WHAT to hold. Immutable shadow. Never reads broker state
Sentinel        HOW MUCH of it to hold. Never reads realized exposure
Execution       the only layer that touches a broker
```

The membrane is one-directional. Fills, outages, halts and rejects are inputs to
execution and reconciliation. They are never inputs to Wealth Core or to the
controller.

---

# Required Reading Before Coding

```text
docs/sentinel-deployment.md          operational ground truth. READ FIRST
docs/sentinel-architecture.md        strategy/controller architecture
docs/sentinel-execution-contract.md  the execution and recovery contract
```

Read `docs/sentinel-execution-contract.md` before touching ANYTHING under
`sentinel/execution/`, `sentinel/binding.py`, `sentinel/handover.py` or the
feed's publication/repair modules. It carries the command-identity, UNKNOWN,
observation-completeness, corporate-action and backup-restore rules, and every
one of them has a falsifier in `tests/sentinel/`.

For any task touching **Wealth Core** read these FIRST, in this order — several
of the rules in them are release-blocking:

```text
docs/wealth-core-certification.md   what is proven, what is owed, NO-GO status.
                                    READ ITS "Resuming this work" HEADER FIRST
docs/wealth-core-v1.md              the design, the four price domains
docs/wealth-core-defense-plan.md    the shadow-book defensive overlay
docs/wealth-core-test-rewrite.md    how the suite got here (history)
```

---

# The legacy eradication (2026-08-11)

Stocker's runtime is **deleted**, not merely unused. Removed: the ~16-service
compose graph (api, pipeline, portfolio-builder, llm-vetter, llm-gateway,
evaluator, risk-service, trade-executor, scheduler, alpaca-sync, av-ingestor,
dashboard, db-migrator, strategy-validator, bt-scheduler, the simulators, the
Ollama profile), the target-portfolio strategy engine, the intent/delta lineage,
the alembic schema, the strategy YAMLs, and every test tier that exercised them.

```text
git checkout stocker-legacy-2026-08     # the last intact state, at 81ad9c1
```

**Mine that branch; do not resurrect from it.** The invariant tests there encode
outages that actually happened and are worth reading before you re-solve a
problem. But anything reintroduced must be rebuilt against the current contract —
the IBKR adapter is the cautionary case: its defects were properties of a design
built against the retired broker surface.

The archive is a BRANCH rather than the tag CLAUDE.md originally specified,
because this environment's credentials return HTTP 403 on tag push. If you can
create the tag, do: `git tag -a stocker-legacy-2026-08 81ad9c1`.

## What survived, and under which classification

```text
PRODUCTION
  sentinel/                                the appliance
  shared/stock_strategy_shared/wealth_core/ the certified engine
  shared/stock_strategy_shared/broker/     base + alpaca, for the MIGRATION only
  docker-compose.sentinel.yml

CERTIFICATION-ONLY — must never enter the production dependency graph
  services/bt-engine/     Wealth Core rehearsal endpoint. main.py was reduced to
                          that surface in 2026-08: the eradication deleted the
                          modules its retired backtester API imported, so the
                          service could not START and the endpoint it was meant
                          to preserve was mounted on a dead entrypoint
  services/bt-data/       Sharadar corpus loader for the certification stack
  services/backtester/    wealth_core_replay.py, the corpus-parity oracle.
                          main.py, config_replay.py, parity.py and _vendor/ are
                          DELETED — unreachable, unimportable, and nothing here
                          is resurrected merely to satisfy an old entrypoint
  docker-compose.backtest.yml
  tests/support/          the ephemeral-Postgres fixture
```

`sentinel/` imports exactly 21 shared modules and cannot reach anything else.
That closure is the boundary; verify it rather than assuming it:

```bash
python -c "import ast,pathlib;from collections import deque; ..."   # see the
# closure script in the eradication commit message
```

---

# Wealth Core: the standing constraints

`stocker_wealth_core_v1` is a stateful-ownership book (25 slots, 4% admissions,
30% trailing stop, one-time 119-session review, 21-session cooldowns). It is
**built and NOT ACTIVATED**. Read docs/wealth-core-certification.md before doing
anything with it.

1. **NO-GO stands.** The remaining certification steps need the NAS and the
   authoritative Sharadar corpus.
2. **Never edit a scoring formula in place.** Both volatility profiles exist as
   NAMED profiles and `volatility_profile` is in the config hash.
   `log_returns_certified_v1` is the only basis for a certified artefact.
3. **The golden fixture is re-pinned only deliberately, once per batch of
   semantics, with the movement decomposed.** A test patched until it passes
   records whatever the code now does.
4. **A guard is not done until it has been shown to fail.**
5. **The golden fixture is INTENTIONALLY UNPINNED right now** — three tests in
   `tests/wealth_core` fail on the pin and nothing else. Do NOT re-pin to make
   them green. The sequence is: rehearsal → explain all eight episodes and the
   $283.04 → prove economic outputs unchanged → fresh-interpreter guard in a
   valid environment → ONE re-pin. See docs/wealth-core-certification.md.
6. **NO HEADLINE CAGR WITHOUT THE TERMINAL WATERFALL.** A performance number may
   not be reported, quoted or persisted without the settlement counters AND the
   episode-level terminal audit beside it. `exact_terminal_settlements = 0` is
   NOT a pass: ACTIONS carries no per-share consideration, so that branch is
   structurally unreachable and remains fixture-only.

---

# Data: Sharadar only

Alpha Vantage is retired with the rest of Stocker. Sentinel reads Sharadar
(Nasdaq Data Link) — SEP, ACTIONS, TICKERS. SF1 is deliberately not fetched:
Wealth Core consumes no fundamentals.

The four price domains, and getting them wrong is silent:

```text
SEP.close        SPLIT-adjusted, DIVIDEND-unadjusted   -> the SIGNAL domain
SEP.closeunadj   the actual as-traded price            -> MARKING + EXECUTION
SEP.open         SPLIT-adjusted, like close            -> scaled to as-traded
SEP.closeadj     split AND dividend adjusted           -> READ BY NOTHING
```

`closeadj` is a total-return series and is enforced-unread by test.

**The corpus is published atomically under a monotonic version** and the engine
pins one per session. An ingest RUN is not a corpus VERSION — a run that fails
halfway has a run_id and must never be citable. Detection tier only: it answers
"a decision read v47 and the corpus is now v52", not "show me v47".

---

# Safety Rules

```text
paper trading only — sentinel/config.py refuses api.alpaca.markets, no override
no live credentials in repo
no secrets committed
an uncertain broker outcome is UNKNOWN, never FAILED
no autonomous broker-native close_position
the long-only unlevered envelope is asserted at the execution gate
```

---

# Testing

`pytest.ini` sets `--import-mode=importlib`. Run the suite with:

```bash
bash scripts/run-tests.sh -q      # every suite in its own process
```

`make test` installs the dependency contract first. A suite whose dependency is
missing ERRORS at collection, which reads as a broken repository rather than an
unprovisioned runner.

Every rule in the execution contract has a falsifier. When you add a rule, add
the test that fails without it — and check that it actually fails.

---

# Coding Style

```text
Python 3.12
Pydantic for schemas, pytest for tests, Postgres for durable state
Decimal for every quantity and price that reaches a broker
```

Keep modules small and clear. Prefer explicit schemas and typed models. Avoid
clever abstractions. Do not add unnecessary dependencies.

---

# Final Design Principle

```text
Deterministic strategy state
  + versioned input history
  + one execution membrane
  + recoverable command identity
  + convergence after absence
```

Preserve this boundary throughout the codebase.
