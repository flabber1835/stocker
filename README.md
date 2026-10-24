# Sentinel

This repository contains one production architecture. Stocker is retired.

```text
Market data   Alpaca SIP bars/actions and OpenFIGI classification
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

The current owner-selected operating profile is local PAPER. Follow the
[current operating contract](docs/sentinel-deployment.md) and the
[resumable local delivery guide](docs/local-paper-delivery.md) for installation.
The dashboard is read-only; starting it does not enable execution. Existing
credentials stay in the private installed environment, outside the repository.

Use [the testing guide](docs/testing.md) for targeted tests, the pinned local
test lens, and explicitly requested complete runs. CI changes and retained
historical evidence are governed by [CI hardening](docs/ci-suite-hardening.md).

Historical replay and strategy research live outside the production trader.
The pre-separation certification environment is preserved at
`research/backtester@7f12174273dfa071a25614d2c4a1be8ebfdfbc3a`. Construction of
the standalone certification system is deferred. Automation permission is durable
account-bound state; neither repository documentation nor process startup grants
it. Actual runtime/image identity, current authority and financial evidence are
checked independently.

Safety boundaries:

- paper endpoint allowlisted; no live-trading override;
- no autonomous migration, startup liquidation, or startup broker action;
- UNKNOWN submissions are reconciled by durable command identity;
- PostgreSQL owns state, account binding, plan and execution journal;
- backups, archives, restore drills and backup verification remain suspended by
  the owner; installation must not enable or invoke them;
- preserve the canonical database, book, command journal and notification history;
- never use Compose `--volumes` against durable state.

The owner currently authorizes qualified local-branch delivery to PAPER. The
historical PR/release workflow stays suspended until explicitly reinstated; see
`AGENTS.md`. The [operational architecture decision](docs/operational-architecture-20261023.md)
defines bounded verification, data sharing and controlled application handoff.
Preparation for future real-money operation does not enable a live endpoint.
