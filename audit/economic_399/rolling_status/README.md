# Rolling status: retained input memory review

Reviewed base: `e3dfb033d25ed68e5e1f6d2386285afabc62e801`, fetched from
`flabber1835/stocker:main` before editing and again before delivery. Branch:
`codex/rolling-status-resource-review`. The PR records the final reviewed commit;
`source-sha256.json` binds the reviewed files independently of that commit.
Design preceded implementation in `docs/rolling-status-resource-bounds.md`.

## Finding and scope

**P2, locally fixed:** `sentinel/rolling_runtime.py:48` calls current-input
assessment during status/classification, including the public
`shadow_runtime.verified_shadow_status` path. It used the full 252-session equity
warmup and then discarded it. `sentinel/core/rolling_inputs.py:253` now streams
the same mapped bars into counts; `sentinel/feed/rolling_go_inputs.py:57` applies
the same readiness clauses. The ordinary material-returning API remains available
to strategy consumers. No cached verdict, publication capability or alternate
economic book is introduced.

Shared setup at `sentinel/core/rolling_inputs.py:157` still verifies all sealed
content. Status remains read-only and publication-pinned. New tests verify these
properties while comparing independent SQL domain counts and unchanged economic
state/command/fill counts. The two assessment reports also match exactly, but
this parity assertion is supplemental to the independent counts and falsifiers.

## Scale measurements

Offline disposable PostgreSQL **17.11**, 5,000 synthetic securities over 300 XNYS
sessions (**1,500,000 stored rows**), minimal issuer references, no action events,
254 required benchmark sessions. Each reader runs in a fresh Python process in a
Docker container limited to **4 GiB and two CPUs**, with no network. Peak RSS below
is the reader process, not container memory or PostgreSQL memory. The panel's
512 MiB budget was not imposed on these probes; no cgroup OOM is claimed.

| Reader/source | Seconds | Python peak RSS (KiB) | Frontier / warmup rows |
|---|---:|---:|---|
| Original materialized reader, base main | 29.1266 | 778,904 | 5,000 / 1,260,000 |
| Compact readiness reader, reviewed source | 28.7027 | 130,592 | 5,000 / 1,260,000 |
| Materialized reader, reviewed source | 29.2290 | 779,316 | 5,000 / 1,260,000 |

All three retain the same 252-session warmup axis. Fixture construction took
46.77, 47.86 and 47.12 seconds respectively, separately from the reader timing.
The compact phase is approximately **128 MiB**, versus **761 MiB** originally.
This closes the avoidable warmup retention, not the full status resource gate.
Full content scans still take about 29 seconds here.

Image: `sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`
(`sentinel-test:ci`); exchange_calendars 4.13.2. Source is mounted read-only and
copied to `/tmp/repo`. Mutation copies never modify the mounted repository.
Synthetic comparison evidence is explicitly marked `COMPARISON_ONLY`; these
measurements do not constitute provider readiness or economic certification.

## Commands and results

Run from the repository root with Python 3.12 and the named local test image.
The retained logs show the expanded Docker command and original workspace.

```sh
python audit/economic_399/rolling_status/run_local.py --universe 5000
python audit/economic_399/rolling_status/run_local.py --universe 5000 --compact
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_rolling_status_inputs.py tests/sentinel/test_rolling_inputs.py tests/sentinel/test_rolling_go_inputs.py tests/sentinel/test_rolling_runtime.py
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_rolling_status_inputs.py tests/sentinel/test_rolling_admission_readers.py tests/sentinel/test_rolling_daily.py
python audit/economic_399/rolling_status/run_local.py mutations
python audit/economic_399/rolling_status/run_local.py go-mutants
python tools/validate_test_responsibility.py --base origin/main --output <scratch>/rolling-status-ownership.json
python -m pyflakes sentinel/core/rolling_inputs.py sentinel/feed/rolling_go_inputs.py sentinel/rolling_runtime.py tools/sentinel_rolling_go_falsifiers.py tests/sentinel/test_rolling_status_inputs.py audit/economic_399/rolling_status/probe.py audit/economic_399/rolling_status/run_local.py audit/economic_399/rolling_status/mutations.py
git diff --check
```

The original regression campaign passed **60 tests**, with **one test-fixture
failure**, in 206.66 seconds: the new stale-frontier test inherited a fixed
calendar from its provider fixture, so its explicit later clock could not take
effect. Restore the real calendar function in that test only. No production
change followed that campaign. The final campaign reruns all seven new tests
alongside admission and daily consumers; its result is recorded below.

Final connected campaign: **52 passed in 259.30 seconds**, including all seven
new tests. The unchanged input/readiness/runtime modules contributed 54 passing
cases to the original campaign; its other six passing cases were the new tests
before the stale-clock fixture correction. These campaign counts overlap.

All **five** new mutants are killed at their intended assertions after a fresh
passing unmodified baseline each: compact production route, payload hash,
dated identity, terminal closure and positive-domain counts. All **11** existing
rolling GO mutants are killed, including frontier/population/domain/issuer,
request/book/target, pin and read-only boundaries. Two source match strings in
that driver changed to follow variable renames; acceptance assertions did not.

Eight Python files parse. Pyflakes reports only the pre-existing `calendar`
import in `rolling_go_inputs.py`, retained because fixtures/consumers use that
module attribute. Ownership passes: **483 modules, zero unowned**. No golden
fixture, capability flag, xfail or provider finality claim was changed.

Raw logs, including the unsuccessful intermediate test, are retained byte-for-byte
inside `raw-logs.zip` to avoid making console whitespace part of the source diff.
`raw-log-sha256.json` identifies each member; `artifact-sha256.json` identifies
the ZIP, source manifest and evidence scripts/design/ledger. Earlier audit
artifacts are untouched.

## Remaining gates and NAS handoff

**Open P2 resource/code review:** full status/checkpoint deserialization, realistic
reference/action history, concurrent requests, repeated full scans and their
latency. No shortcut that skips content validation is authorized. Further review
must bound these phases or retain measured evidence within the agreed operational
budget. The 29-second single input scan is not a qualified status response time.

**Provider/data gates:** C1/F6 cash completeness/finality, F19 native fill authority
and C3 predecessor completeness retain their existing dispositions. This change
does not supply a missing provider guarantee or historical corpus. No 20-year
return/multiple is calculated; preserve all old golden bytes for Step 2.

**NAS-only qualification procedure (not executed):**

1. Require an owner-accepted commit/image and source identity, isolated restored
   PostgreSQL with no broker credentials/network, authoritative full-universe
   price/reference/action manifests, accepted shadow checkpoint and original
   observation ID/capital. A mismatched source identity must refuse; use a reviewed
   continuation/migration, never relabel old certificates. Keep the original
   deployed primary untouched.
2. Run the two test commands and both mutation commands above on the clone's
   accepted test image. Require zero unexpected failures/skips/xfails and every
   named mutant rejected at its intended invariant. Retain source/image hashes,
   raw output, PostgreSQL version and ownership result.
3. On the clone, instrument the entire public call, with the accepted observation
   arguments and environment, using `/usr/bin/time -v python status_probe.py`:

   ```python
   # status_probe.py: DSN must identify only the isolated restored database.
   import os
   from sentinel.feed import store
   from sentinel.shadow_runtime import verified_shadow_status
   with store.connect(os.environ['CLONE_DSN']) as conn:
       result = verified_shadow_status(
           conn, observation_id=os.environ['ACCEPTED_OBSERVATION_ID'],
           starting_cash=os.environ['ACCEPTED_ORIGINAL_CAPITAL'])
       print(result)
   ```

   Retain publication, checkpoint/state hash, readiness clauses, authority identity,
   wall time, process RSS and actual panel-container peak memory/oom events. Repeat
   across cold/warm filesystem cache and representative concurrent panel requests,
   including retained renames and actions. Pass requires unchanged state/command/
   fill counts, consistent verdicts, no OOM and aggregate container use below its
   actual 512 MiB limit, with response times inside the approved panel deadline.
   Record that deadline before the run; absent a deadline, latency is unqualified.
4. In a separate disposable copy, introduce late positive-price payload corruption,
   a dated identity conflict and a stale frontier as in the acceptance fixtures.
   Require refusal rather than a partial successful status. Restart the status
   process and repeat; restarting must not grant fresh or cached authority.
5. Retain realistic dataset manifest hashes and sizes so this can be repeated.
   Missing authoritative inputs, exceeded memory/deadline or unexplained state/
   economic differences fail qualification. No NAS action was taken in this review.

Step 1 and economic certification remain **open**.
