# Synthetic Market Lab v1

Isolated research infrastructure for generating deterministic, causal synthetic equity-market histories with hidden ground truth and a point-in-time public-data membrane.

## Isolation contract

Everything in this lab lives under `research/synthetic_market_lab/`. The generator does not import production strategy modules and does not consume strategy returns, rankings, holdings, selections, parameters, or certified historical evidence. The synthetic adapter reads only a generated `public/` directory. Existing historical data paths are unchanged.

## Phase-1 reference world

The committed configuration at `config/reference-world-v1.json` defines a 20-year, 200-company world with 5,040 business sessions, eight sectors, persistent macro regimes, overlapping shocks, sign-changing factor premia, company-specific fiscal calendars, delayed/restated disclosures, lifecycle events, corporate actions, structured daily prices, and changing liquidity.

Generated world tables are intentionally materialized outside Git. The committed `reference_world/manifest.json`, `validation.json`, `diagnostics.json`, and `replay-proof.json` pin the canonical reference identity, file hashes, statistics, validation result, and deterministic replay proof.

## Reproduce

From the repository root with Python 3.12+:

```bash
python -m venv .venv-synthetic-market
. .venv-synthetic-market/bin/activate
python -m pip install -r research/synthetic_market_lab/requirements-dev.txt
./research/synthetic_market_lab/reproduce_reference.sh
```

The script generates the world under `artifacts/synthetic-market-lab/reference-world-v1` by default, validates it, exports the public-only backtester adapter under its `adapter/` directory, then runs the isolated lab tests.

Generate or validate individual worlds with:

```bash
PYTHONPATH=. python -m research.synthetic_market_lab.cli generate --config <config.json> --output <world-dir>
PYTHONPATH=. python -m research.synthetic_market_lab.cli validate --world <world-dir>
PYTHONPATH=. python -m research.synthetic_market_lab.cli export-adapter --world <world-dir> --output <adapter-dir>
```

## Information domains

`ground_truth/` contains latent macro state, factor premia, company fundamentals/health, shock identities, and causal metadata. It exists for validation and post-hoc research diagnostics. `public/` contains only strategy-visible market observations, disclosures, security identity history, corporate actions, and PIT universe snapshots. `adapter/` is derived from `public/` only.

## Phase-1 gate

The generator is considered valid only when the isolated tests and world validator pass. Strategy evaluation is outside this phase and is not invoked by any lab command.
