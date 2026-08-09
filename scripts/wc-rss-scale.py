"""Peak RSS vs universe size and session count for a Wealth Core run.

    python scripts/wc-rss-scale.py <n_securities> <n_sessions>

Prints: secs sess corpusMB peakMB runMB cand_rows

THE RELEASE GATE for the Stage 2 memory work. Hash parity proves the refactor is
semantically safe; this proves it solves the operational problem. The intended
result after streaming lands is that raising the UNIVERSE still raises memory
(one session is genuinely larger) while raising the SESSION COUNT barely moves
peak RSS. If memory still scales materially with sessions, there is another
retained structure nobody has found yet.

BASELINE, measured on the materialised path 2026-08-08:

    fixed 130 sessions   125/250/500/1000 securities ->  6/11/20/38 MB
    fixed 500 securities 130/260/520/780  sessions   -> 20/43/92/143 MB

    fitted   0.367 KB per candidate row
             0.436 KB per corpus bar

Linear in BOTH, i.e. memory ~ universe x sessions, which is the candidate
payload. Rerun after the integration commit and the second row must flatten.
"""
import resource, sys, gc
from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.run import run_sessions

def mb(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

def scenario(n_sec: int, n_sess: int):
    sessions = [f"S{i:04d}" for i in range(n_sess)]
    meta = {f"P{i}": SecurityMeta(security_id=f"P{i}", ticker=f"T{i:04d}",
                                  category="Domestic Common Stock",
                                  permaticker=f"P{i}")
            for i in range(n_sec)}
    bars = {}
    for t, s in enumerate(sessions):
        rows = []
        for i in range(n_sec):
            px = round(20.0 + (i % 40) + t * (0.01 + (i % 7) * 0.003), 4)
            rows.append(VendorBar(session=s, security_id=f"P{i}", ticker=f"T{i:04d}",
                                  raw_close=px, raw_open=round(px * 0.998, 4),
                                  volume=1_000_000 + i, split_ratio=1.0,
                                  dividend_per_share=0.0, tradeable=True,
                                  unresolved_corporate_action=False))
        bars[s] = rows
    return sessions, bars, meta

base = mb()
n_sec, n_sess = int(sys.argv[1]), int(sys.argv[2])
sessions, bars, meta = scenario(n_sec, n_sess)
after_corpus = mb()
mode = sys.argv[3] if len(sys.argv) > 3 else "materialized"
from stock_strategy_shared.wealth_core.run import run_with_hashes
r, _h = run_with_hashes(sessions=sessions, bars_by_session=bars, meta=meta,
                        starting_cash=1_000_000.0, hash_mode=mode)
peak = mb()
cands = sum(len(s.decision.candidates) for s in r.sessions if s.decision)
print(f"{n_sec:>5} {n_sess:>5} {after_corpus:>10.0f} {peak:>10.0f} "
      f"{peak - after_corpus:>10.0f} {cands:>10}  {mode}")
