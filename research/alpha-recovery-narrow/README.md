# FAST confirmation + externally owned provisional warning

Research reference based on `main@722aa14ae0e452437b80425528ba30fcf133b029`. Strategy code is unchanged from `22ebcf48addadbc7ec4531df415041d1b8674f48`; intervening commits are operational/feed/automation changes.

## Design boundary

`fast_confirmation.py` deliberately does not contain Sentinel recovery or LD-RC code. It emits a confirmed FAST-entry permission and an optional provisional ceiling. Integration order is:

```text
causal FAST evidence -> confirmation gate -> existing native Sentinel
existing native Sentinel -> existing LD-RC -> optional external 55% ceiling
```

The provisional state is not reported to native Sentinel or LD-RC. Clearing it therefore cannot leave a stale recovery episode.

## Reproduce

The backtest runner expects the retained authoritative daily tape and SPY/BIL SFP extract supplied outside the repository:

```bash
python -m unittest -v test_fast_confirmation.py
python run_backtest.py
```

`run_backtest.py` refuses to report candidate metrics unless the current arm exactly reproduces native decisions, LD-RC desired decisions, effective allocations, and daily NAV.

See `RESULTS.md` and `provenance.json` for findings and limitations.
