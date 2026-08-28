# Sentinel

> **`research/backtester` branch:** this is the persistent historical experiment laboratory. Before creating or running any backtest on this branch, read `docs/backtester-experiment-contract.md`. The contract is mandatory: `main` is read-only; experiment inputs must already exist and be hash-pinned on this branch; PIT data may not be synthesized during a backtest; prerecorded tapes/oracles/decision paths may not drive a replay; and every economic result must come from a fresh causal chronological replay.

This repository contains one production architecture. Stocker is retired.

```text
Sharadar      versioned, atomically published market-data history
Wealth Core   deterministic alpha engine and immutable shadow book (WHAT)
Sentinel      deterministic exposure controller (HOW MUCH)
Execution     the only broker-facing layer; Alpaca paper accounts only
```

Sentinel prepares a durable current plan separately from executing it. Account
migration, plan preparation, inspection, and paper submission are distinct
operator commands. Ordinary Compose startup cannot migrate an account or submit
an order.

Start with the operational ground truth:

- `docs/sentinel-deployment.md`
- `docs/sentinel-paper-activation.md`
- `docs/sentinel-nas-go-validation.md`
- `docs/sentinel-architecture.md`
- `docs/sentinel-execution-contract.md`

Common non-trading commands:

```bash
cp .env.example .env                 # fill required secrets locally
mkdir -p "$SENTINEL_BACKUP_DIR/wal" "$SENTINEL_BACKUP_DIR/base"
make sentinel-up                     # PostgreSQL + read-only loopback panel
make status
make check-data
make test                            # process-isolated repository suites
```

The Wealth Core rehearsal stack is defined in
`docker-compose.backtest.yml`. It contains only PostgreSQL, the Sharadar data
service, and the deterministic engine. It has no broker-facing service. The
separate Stage 4 Sentinel automation overlay is installed disabled and killed,
requires immutable image identities plus signed authority, and is never part of
the rehearsal stack.

Safety boundaries:

- paper endpoint allowlisted; no live-trading override;
- no autonomous migration, startup liquidation, or startup broker action;
- UNKNOWN submissions are reconciled by durable command identity;
- PostgreSQL owns state, account binding, plan and execution journal;
- every supported Sentinel Compose invocation requires second-target WAL
  archiving and verified backup readiness;
- never use Compose `--volumes` against either durable database.

All changes arrive through a pull request targeting `main`; see `AGENTS.md`.
