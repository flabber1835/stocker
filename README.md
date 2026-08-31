# Sentinel

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

Historical replay and strategy research live outside the production trader.
The pre-separation certification environment is preserved at
`research/backtester@7f12174273dfa071a25614d2c4a1be8ebfdfbc3a`. Construction of
the standalone certification system is deferred. The Stage 4 Sentinel
automation overlay remains installed disabled and killed and requires immutable
image identities plus signed authority.

Safety boundaries:

- paper endpoint allowlisted; no live-trading override;
- no autonomous migration, startup liquidation, or startup broker action;
- UNKNOWN submissions are reconciled by durable command identity;
- PostgreSQL owns state, account binding, plan and execution journal;
- every supported Sentinel Compose invocation requires second-target WAL
  archiving and verified backup readiness;
- never use Compose `--volumes` against either durable database.

All changes arrive through a pull request targeting `main`; see `AGENTS.md`.
