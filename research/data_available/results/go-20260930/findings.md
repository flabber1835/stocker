# September 30 GO anomaly: prototype replay

The unchanged stateful snapshot prototype avoided the observed whole-universe
refusal when the affected securities were unheld. It retained the missing prices
and separate native identities, excluded the affected names from entry, and
continued trading unrelated candidates. A hypothetical affected holding with no
price still blocked admissions and retained its identity, quantity and cash.

## What was reproduced

The supplied GO ZIP has SHA256
`e308ed05c5da66ba08846b28fd268b9c67a5549e1511cdcc254491c33e29a6fa`
and names deployed commit `90a068a90961c8b8e984ae2e2ae8a9ea0fa75445`.
Its September 24 coverage failure expected 5,875 eligible native identities but
received 5,874, missing FJDIU / 6401378. The FJDI/FJDIU rename relationship was
rejected because its anchors had separate identities and categories.

The control ran the actual deployed coverage and identity code from a read-only
Git archive. It used the two observed listings, six actions and relevant SEP
row from the owner's later source diagnostic, plus 5,873 explicitly synthetic
unaffected listings. It reproduced the failed date, expected/received counts,
missing key, refusal type, action source IDs and complete identity diagnostic
hash `b04429dc1f57782a0076b8c813e8a36120e315aea858ec6f657b991a8bbcfeb9`.
The diagnostic's integer permatickers were converted to text, as in the bulk
CSV path. No coverage exception was added or disabled in the deployed code.
The zero projection digest in the control identifies a constructed projection;
it is not the original NAS projection digest.

## Prototype result

Each close from September 23 through September 29 received a newly built
300-XNYS-session snapshot. The seven observed FJDI/FJDIU rows were retained;
30 synthetic mature candidates supplied an independently useful trading control.
The control without either affected name was run alongside the anomaly case.

| Check | Result |
| --- | --- |
| Whole-window processing | All five closes completed, none blocked |
| Unrelated signals | Exactly equal to unaffected control |
| Strategy state, pending orders and ledger | Exactly equal after every close |
| Simulated next-open fills | 20, identical to unaffected control |
| FJDI/FJDIU admissions | Zero; neither has the required 127 sessions since listing |
| Missing FJDIU September 24–25 prices | Remained missing |
| Later FJDIU September 28–29 rows | Accepted as observations, still insufficient for entry |
| Identity handling | Native identities stayed separate; no history transferred |
| Same anomaly under unrelated names/IDs | Same behavior, no ticker-specific rule |
| Hypothetical 100-share affected holding without a mark | Retained; equity unresolved, no orders/fills or invented cash |

No prototype or production decision/accounting implementation needed a fix.
The cash and performance values of the synthetic control are not investment
results. The hypothetical holding is not claimed to be an actual NAS position.

## Limits and validation

The source diagnostic was observed at 14:50 UTC, about 21 minutes after the
14:29 GO bundle. It matches the anomaly but is not a frozen copy of the entire
failed export. Neither input contains the full NAS histories or holdings.
This establishes how the existing prototype handles the observed condition at
its snapshot boundary; it does not establish an end-to-end NAS GO pass.
Production GO still calls its production acquisition boundary. Backup budgets,
worker deadlines, broker reconciliation and source availability were not tested
by this replay. Later held corporate-action processing was not simulated.

Executed in Python 3.12, Docker image `sentinel-test:acquisition-data-local`,
with networking disabled and a 1 GiB memory limit:

```sh
PYTHONPATH=/work:/work/shared python -m pytest research/data_available -q -p no:cacheprovider --tb=short
# 39 passed in 9.72 seconds (six new tests)
PYTHONPATH=/work:/work/shared python -m research.data_available.observed_go --output research/data_available/results/go-20260930/prototype.json
# all four original/renamed, held/unheld scenarios PASS
```

For the deployed control, `/control` contained `sentinel/` and `shared/` from
`git archive 90a068a90961c8b8e984ae2e2ae8a9ea0fa75445 sentinel shared`.
The working directory was `/control`, avoiding current source on the import path:

```sh
PYTHONPATH=/control:/control/shared python /work/research/data_available/observed_go.py --coverage-control --output /work/research/data_available/results/go-20260930/deployed-control.json
# REFUSAL_REPRODUCED
```

Output paths must not already exist. `deployed-control.json` records the executed
coverage module hash; both outputs record the fixture and bundle hashes. The
prototype was unchanged from research commit `c7c9d26a83dba3dc341011596116d45fe24a7214`,
which includes verified main `74b1158519a870e693af4c4361fc080998e3eac0`.
