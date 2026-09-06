# Execution record: SPY / IWM observation experiment

RESEARCH / NOT CERTIFIED. This record supplements DESIGN.md before economic replay.

## Calendar correction

The independent five-year launch is **2021-08-02 through 2026-07-31**. August 2 is the first equity session on or after the July 31, 2021 anniversary. This supersedes the mistaken July 30 date in the initial design. The portfolio, pending orders, receivables, cooldowns, raw portfolio return/drawdown history and controller states initialize afresh at launch. The preceding 260 canonical sessions warm indicators only. The 20-year run preserves the original 2006 warmup and 2006-07-31 measurement start.

## Data already frozen

Data-only run: https://github.com/flabber1835/stocker/actions/runs/34011985844

The immutable observer package and per-file hashes are committed at backtester/data/champion-spy-iwm-observer-inputs-v1.json. Data-only artifact 9982753298 has ZIP SHA256 f1d2333b0326345f1e86e791f546001a8a23b34a2436aa70c3eb55b9085af51d. SPY, IWM and VIX cover every corrected-reference measurement session. Retained SPY normalized NAV differs from the corrected reference by at most 7.976e-13; daily return differences are below 8.882e-16. These are input cross-checks, not a new economic result.

## Fresh causal execution

The experiment generates a fresh raw Wealth Core book from the frozen canonical package. The unchanged corrected Champion control, Native-only control and all 81 declared variants advance on each session before advancing the date. No prior holdings, decisions or NAV file is read by the economic run. Each arm maintains separate controller state, pending target, effective exposure and account NAV.

The same frozen Native portfolio protection is preserved across all arms. The new market observations are independent of security classifications; the actual portfolio guard retains legitimate dependence on holdings. Unheld candidates may still affect rankings and the portfolio path. Certification is separate from this experiment.

The full20 job downloads the retained corrected daily artifact only after the fresh replay completes. It then requires numerical parity at 1e-12 tolerance and exact holdings, ranking and controller-state hashes. Internal reconstructed-control accounting parity is checked independently before any result is emitted. Original control class AST hashes and source seams are validated.

## Local tests completed before launch

Command:

```bash
OBSERVER_ASSEMBLY_WITNESS=/mnt/data/spy_iwm_baseline/generated-replay.py \
PYTHONPATH=. python -m unittest tests.backtester.test_research_champion_spy_iwm_observers -v
```

27 tests passed locally. The retained generated source was used solely as a local seam/accounting test witness. The runner omits OBSERVER_ASSEMBLY_WITNESS and assembles directly from pinned harness sources and the frozen runtime. Local full assembly required the absent sentinel runtime; that check is delegated to the runner. A new test initially expected a SPY-rebound release while external stress simultaneously re-entered a latch. The test was corrected to isolate recovery with healthy observations; controller semantics were preserved.

Coverage includes future-price mutation/prefix invariance, price-scale invariance, exact lookback/ddof, duplicates and missing observations, data hash falsifiers, VIX prior-session lag, grid bounds, independent IWM stress, VIX boundary conditions, native/drawdown entry guards, eight-session persistence, healthy-streak reset, strict rebound threshold, independent controller state, no same-close execution, frozen overnight/intraday cash and turnover accounting, fresh launch refusal on inherited state, and classification/leadership-input invariance.

## Reproduce

Use the exact experiment SHA and frozen runtime 887f479b15ad861313da666ad698034d3847121c, install the runtime's hashed requirements, extract both digest-addressed packages named by canonical-pit-20y.json and champion-spy-iwm-observer-inputs-v1.json, set CANONICAL_PIT_DATASET to the canonical directory, and run:

```bash
python -m unittest tests.backtester.test_research_champion_spy_iwm_observers -v
python backtester/research_champion_spy_iwm_observers.py --output output/full20 --mode full20 --input-root observer-data
python backtester/research_champion_spy_iwm_observers.py --output output/fresh5 --mode fresh5 --input-root observer-data
```

After full20 completion only:

```bash
python backtester/research_champion_spy_iwm_observers.py --output output/full20 --check-reference retained-reference/daily.csv.gz
```

The workflow pins all checkout/actions references and source/runtime hashes. It has read-only repository/package permissions. It does not write to main, certification branches or the parallel SPY/VIX/R3000 research branch.

## Interpretation boundaries

The 81-point grid and central points are predeclared. Reporting every variant does not make the best point out of sample. Neighbor dispersion evaluates local sensitivity, and a single fresh five-year launch is a first start-state check. Repeated independent launches and full-universe perturbation replays remain further robustness work. External-input independence is tested directly; economic invariance to changed stock selection is not claimed.

All new results retain RESEARCH_NOT_CERTIFIED. Original vendor publication vintages for adjusted ETF histories and VIX remain unproven. A successful workflow confers no strategy promotion authority.
