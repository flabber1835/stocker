Investigate why the current production-kernel replay performs materially worse
than the retained 56.27x research run. Determine whether the difference comes
from software defects, initialization, eligibility/data, strategy changes, or
accounting assumptions. Do not assume either run is correct.

Repository: flabber1835/stocker. Replay PR: https://github.com/flabber1835/stocker/pull/426.
Production revision: 624395dd04c48af7de3a8930cfd586ca2cc81245 (#425).
January harness revision: c98dc7b57b65f47f64ad72f6ecc775515fafd12d.

Keep this investigation read-only. Do not change existing source, inputs,
supplements, checkpoints, branches, containers, or output files. No NAS or real
broker access. Follow AGENTS.md and required Wealth Core reading. Spend at most
30 minutes initially, prioritizing causal evidence over another full backtest.

Worktree: C:/GitHub/stocker/.codex-tmp/bounded-production-replay-worktree
Evidence: C:/GitHub/stocker/.codex-tmp/january-replay-evidence
Read docs/bounded-production-replay.md and
audit/economic_399/january_replay/README.md. Each segment has daily.jsonl,
identity.json, status.json and checkpoints. january-001 ends November 16, 2007;
january-002 continues the same book and stops October 29, 2008. Supplements
and exact blocking-action evidence are retained alongside the segment folders.

Both scenarios start with USD 100,000 cash in January 2006, form their books
naturally, and first buy July 6. Measurement starts July 31 without a reset.
Current July baseline NAV is USD 90,886.70559160098. Verify the research
formation and baseline independently. At October 29, 2008, current results are
0.9498118143x / -2.26468673% CAGR; same-date reference is 1.3135306605x /
12.89926342%. Full reference is 56.2653493366x / 22.3236000232% CAGR.
Never compare a partial CAGR directly with the full twenty-year result.

Reference branch: research/champion-certification-20y-v1.
Reference commit: 2a1bd486241ae524eac395490b135cc79715e497.
Reference artifact directory:
research/champion-certification-20y-v1/results/34544522249-1/
Inspect core/champion.py, core/engine/daily.csv.gz, portfolio-composition.csv.gz,
transactions.csv.gz, summary.json, champion-daily.csv.gz and PROVENANCE.json.
The current harness retains research/bounded_20y/reference-daily.csv.gz.
Use git show/ls-tree or a separate checkout; never switch this worktree.

Known differences to verify: current unknown classifications remain ineligible,
while research had a classification overlay; historical accounting carried
missing prices and proxy-settled some missing terminals after ten sessions,
while its harness removed a missing-mark abort; current production refuses
unresolved valuation and includes economic-path fixes. Read the action ledger
for researched cash/stock corrections and remaining IKN date/bar conflict.
Corrections here are research inputs, not broker settlement evidence.

Deliver a concise attribution:

1. Find the earliest divergence in eligibility, ranks, orders, holdings,
   fills/costs, controller exposure and NAV, starting during formation.
2. Separate Wealth Core differences from controller and accounting differences.
3. Identify the largest contributors to the matched-date gap with quantities
   and dollar effects where supportable.
4. Trace suspected defects to exact code and independent economic oracles.
   A difference alone is not proof of a bug.
5. Use only small deterministic reproductions or bounded counterfactuals.
   Preserve golden artifacts; never repin, relax guards, or silently repair data.
6. Report confirmed defects, intentional differences and unresolved hypotheses
   separately, with file/line evidence and recommended next actions.
