# Economic audit 399: pre-NAS review and qualification handoff

**Certification remains BLOCKED.** This record supplements the
[finding ledger](economic-audit-399-remediation.md), not the production certificate.
Review started at PR #402 head `97a5fb45f010848dc68569b91b611494a589c59a`,
on independently fetched main `aff4461d9af6d4a7367018768fda18d948958b49`.
The complete PR changes, original issue findings and retained acceptance probes
were reviewed; the last test-only commit was not treated as the review scope.
No NAS access or real broker requests occurred. All HTTP broker responses used
below are deterministic fixtures. Public provider documentation was read.

## Additional defects found

| Finding | Severity | Defect and correction | Independent acceptance |
|---|---|---|---|
| C2 compound event | P2 | `controller/terminal_returns.py:values` omitted the source's same-session split before terminal consideration. A 2:1 split followed by $50 cash per new share falsely halved a $100 notional holding. Apply the source share multiplier first; do not double-apply a delivered-security split. Champion economic schema is now `audit399-decimal-terminal/2`. | Six cash/stock/mixed forward/reverse split cases; warmed canonical book and production kernel for held and unheld sensor members, with JSON restart and unchanged prior state. |
| F19 across observations | P2 | `execution/reconcile.py` validated each response independently. Replacing a complete ten-share fill with a different native ID journaled twenty shares and still returned RUNNING. `fill_integrity.validate_durable` validates retained plus incoming economics and requires complete responses to include retained identities before observation publication. | Previously accepted history followed by replacement IDs refuses repeatedly and preserves original rows; six-then-four progression over fresh SQL connections retains ten shares/$1,000 and exactly two alerts. |
| F14 missing origin | P2 | `restore_validation._rolling_closure` accepted surviving strategy history with a missing origin as an uninitialized restore. It now checks the existing lineage inventory before returning an empty result. | Actual SQL loss of the origin fails; intact, genuinely uninitialized, damaged HMAC and damaged snapshot cases distinguish the boundaries. |
| F19 diagnostic retention | P3 | Malformed quantity/price/execution-time parsing could refuse without retaining the raw event. It now uses the account-bound diagnostic path; no economic rows are written. | Invalid decimal, zero/negative economics and malformed time retain the offending field and no fills. |
| C1/F6 candidate wire/evidence | P2 | The candidate sent `until_id` without required `since_id`. It now repeats a valid timestamp-bounded request and explicitly reports a repeated snapshot, not fixed-frontier replay or finality. Unaccepted semantics advance to V2; capability bits stay false. | Provider parameter-rule falsifier failed before the fix; changed/missing/late rows refuse, and repeated empty responses explicitly carry no finality. |

Corrected source anchors at the reviewed code commit: C2
`sentinel/controller/terminal_returns.py:8`; F19 durable union
`sentinel/execution/fill_integrity.py:68`; F14 origin check
`sentinel/restore_validation.py:93`; candidate bounded replay
`sentinel/execution/alpaca.py:1897` and limited evidence labeling at line 2195.

The first two new probes failed **7 cases** on the unfixed implementation; the
missing-origin probe separately failed **1 case**. These red results are retained.
The independent provider parameter-rule probe failed **1 additional case**.
Removing each economic/restore guard must break its passing acceptance test.
No golden bytes, xfail declarations, capability flags or live safety settings
were changed. Adapter registry prose was corrected because it overstated cash
and restore authority that the actual capability gates refuse.

## Requirement-to-caller review

Paths below are under `sentinel/` unless prefixed `shared/`. The existing ledger
lists exact acceptance files; this table records what those tests establish and
where an apparently passing test would be insufficient.

| Findings | Production and durable path reviewed | Local disposition and limit |
|---|---|---|
| F1/F3 | `rolling_runtime` → `rolling_daily` → `core/rolling_continuity.prepare` → dated `SnapshotReferences` → checkpoint | Common rational source-precision interval, exact raw economics and historical alias boundaries; current rename acceptance and nonuniform-revision refusal. A factor-of-two-only fixture is insufficient. Provider historical identity provenance remains a separate data gate. |
| F2 | `wealth_core.v5.admission/opening_quantity` → canonical adapter and `execution/opening_sizing` | Both intended budget and affordability floor the same exact decimal-spelled quotient. The 25-share $2,582.0795 oracle and adjacent prices/budgets exercise both callers. Canonical float state is not claimed to be a Decimal ledger. |
| F4 | `rolling_go_inputs`/`operational_snapshot` → `rolling_jobs.enqueue/expire` | Request lock, retained expiry and one successor cover the original stranded first attempt. This does not clear #400's supervisor handling of an active lease/source wait. |
| F5/F7 | executor SEND_PENDING/outcome commits → automation result routing/callback death → recovery and journal | Mixed refusal and callback death preserve observation obligations; absent exact-key reads preserve UNKNOWN and block replacement. Positive original-order facts can converge. No finite local wait proves request finality. |
| F8 | configured `AssetIdAlpacaExecutionBroker` → nested observation → candidate SSE | Real nested call is blocked without the accepted capability, including when the fake endpoint is reachable. Fixture opt-in is explicitly simulator-only. Availability is not completeness. |
| F9/F10/C2 | canonical close plan serialization → kernel → shadow weights/controller; peak stop → pending exit → next-open ledger | Sub-cent NAV, exact inclusive stop, terminal price-return consideration and same-session split are independently checked. Calling the same kernel twice only proves restart equivalence; it is not an economic oracle. |
| F11 | cash grace cursor and strict recovery completion → persisted numeric identity | Equal decimal spellings retain one identity; changed economics still refuse. No elapsed grace is converted into provider finality. |
| F12/F13 | alert service incident enqueue → outbox claim → Web Push per-device result → final attempt result | Leader-independent incident and unique process holder; attempt and expiry fence final and per-device writes. A new HTTP takeover test proves the old response cannot finish its successor. HTTP acceptance/SQL-ack loss can still cause a repeated physical push; stable tag is not exactly-once delivery proof. |
| F14/F15 | restore entrypoint → rolling origin/daily/authenticated shadow/current snapshot; publication commitments → retained coverage → action reader | Missing origin/coverage, damaged current payload and authenticated history are checked. Historical price retirement remains permitted. Local physical replay is structural evidence, not predecessor broker completeness. |
| F16 | PAPER preparation → `paper_performance.scan_entitlements` → complete source payer/alias set → scoped price requirements | Unrelated sparse payers do not demand absent prices; affected owned payers must be priced. Native ownership coverage is checked before permanent quarantine is written. No broker cash is invented. |
| F17/F18 | current/adopted/planless PAPER recovery → earliest durable command basis → retained action lookup → journal reconciliation | Newer shadow state does not reinterpret old target intent. Original command quantities remain native; expected holdings age through complete action history, including exited positions and BIL. Authorization seams in fixtures do not qualify deployed issuance/leases. |
| F19 | native parser → exact order join → response and durable-union validation → observation/fill journal → notifications/entitlement scanner | Identity, chronology, cumulative quantity/notional, repeated reads and partial progression covered. Corrections/busts refuse append-only accounting; no reversal implementation or accepted average-price rounding rule is claimed. |
| C1/F6 | candidate cash producer → `broker_cash` rows/cursor/baseline transaction → `paper/cash` | Generic accepted-input arithmetic and crash/retry atomicity are locally testable. They do not establish that the actual provider supplies an accepted complete/final producer. |
| C3 | physical incarnation → binding takeover epoch → `recovered_order_policy` → strict watermark | Fresh process rejects prefix-only ownership and fences takeover epoch >1. Existing local journal provenance and restored bytes cannot prove omitted predecessor broker activity. |

## Gates that local passing tests cannot close

### Provider and implementation gates

* **C1/F6, P1 certification blocker:** `sentinel/paper/cash.py:188` and
  `sentinel/execution/alpaca.py:1938`. Production financial activity remains
  unaccepted. A deposit, fee or distribution cannot be inferred from an empty
  response or normalized away after cash grace. Require an account-bound,
  exhaustive cursor/replay contract, correction semantics, cash classification,
  and a separately evidenced fixed-close finality horizon. The generic cash
  fixtures explicitly supply this contract; the production adapter does not.
* **F19, P2 accounting/capability blocker:** `sentinel/execution/alpaca.py:1724`
  and `sentinel/execution/fill_integrity.py:16`. Candidate history remains
  disabled. Corrections/busts require reviewed reversal/replacement accounting;
  the exact cumulative-average comparison deliberately refuses undocumented
  rounding rather than choosing a tolerance. Late publication and endpoint
  coherence remain provider questions, not proof supplied by a local replay.
* **C3, P1 restored-transport blocker:**
  `sentinel/execution/recovered_order_policy.py:75`. Keep the takeover fence.
  Ordinary pagination, DAY expiry, a Sentinel-looking key and a restored local
  table cannot authenticate missing predecessor commands or their outcomes.
  Need a provider-backed account/interval completeness contract plus retained
  command preimages and an accepted recovery protocol. No automatic adoption
  or capability promotion is added here.

Alpaca's [Activity SSE guide](https://docs.alpaca.markets/us/docs/activity-sse)
distinguishes publication IDs, economic IDs and execution time, and describes
backfills plus correction/bust links. Its timestamp-filtered snapshot is not
proof that no later financial event can appear. The
[Trading SSE reference](https://docs.alpaca.markets/us/reference/subscribetoactivitiessse)
explicitly lists the paper endpoint and requires a lower cursor with `until_id`.
Endpoint existence is established; permissions and accepted completeness on
the exact account remain untested. The repaired initial candidate makes only
two identical timestamp-bounded reads and labels that limited evidence honestly.
The [Trading order-list reference](https://docs.alpaca.markets/us/reference/getallorders-1)
documents bounded pagination and submission-time filters. Neither reviewed page
establishes the fixed-close, request-finality, predecessor-completeness or
cumulative-average precision guarantees required here. This is a statement of
the evidence found, not a claim that the provider can never offer a guarantee.

### #400 dependencies: code work is not NAS-only evidence

The relevant inherited blockers remain on
[issue 400](https://github.com/flabber1835/stocker/issues/400). PR #402 does not
claim to remediate that entire autonomy audit. A8/A9/A10 and the A21 restore
extension overlap F5/F3/F1/F14; their local corrected claims are bounded above.
The other issues below must retain explicit code dispositions before unattended
qualification. A physical NAS run alone cannot repair them.

| Dependency | Severity retained | Current source / remaining requirement |
|---|---|---|
| A1/A17/A24/A27 | P1/P2 | Supervisor database/log I/O, callback deadlines, deployment health and post-retention diagnostics must have independent bounds. `automation_supervisor.py`, `shadow_supervisor.py`, deployment driver and `feed/retention.py` remain separate review/fix work. |
| A2/A3/A4/A11/A13/A20 | P1 | `rolling_runtime.service_advance`, shadow supervisor, automation dependency classification and backup guard must recover missed sessions/opens and transient outages without latching away durable obligations. The F5 execution exception fix does not clear every callback phase. |
| A5 (original)/A6 (backup duplicate) | P1 | Backup guard refusal is safe; recurring base-backup scheduling/rollover still needs autonomous lifecycle implementation and target evidence. |
| A6 notifications/A18/A19/A25 | P2 (A19 P2) | `automation/outbox.py:558` still dead-letters at the attempt limit; `web_push.py:432` still uses `all()` for mixed recipient retryability. Endpoint rotation, recurring incident identity, missing-control alarms and panel event-loop SQL remain separate defects. Per-attempt fencing does not solve delivery continuity. |
| A12/A14/A15/A16 | P1/P2 | Whole-snapshot status cost, recent SIP entitlement admission, returning-security state and held spinoff continuation need their own accepted dispositions; a tiny synthetic universe cannot establish production resource bounds. |
| A21/A22/A23/A26 | P1/P2 | Rolling first-install/admission/readers, DUAL mode propagation, standby fencing around migration and effective Dockerfile selection remain deployment-code dependencies. Restore validation fixes only the explicitly shared F14 subset. |

The original audit's global mechanical candidate inventory is not equivalent
to semantic proof. This PR review and its targeted campaigns do **not** certify
exhaustion of all indirect callers, arbitrary compound failures, all #400/#401
paths or every production-sized event sequence. Those open review obligations
must not be relabeled as provider-only or NAS-only blockers.

## Historical data and reference disposition

Both immutable historical source `5afba080859f25ea65fdb82da9ba54b442bac368`
and current source were freshly replayed on the unchanged synthetic golden
scenario. Six retained independent reconciliation tests pass. Historical cash
is $34,868.23464; current cash is $34,824.73117999994 (exact event arithmetic
$34,824.73118). The three changed purchases at ledger indexes 35, 36 and 39
add $239.57934, -$239.55932 and $43.48344 of spend: total **$43.50346**.
The documented exit-session age-zero cooldown explains their dates. Earned
unsettled receivables explain the separate $167 ex-date NAV difference.
Both runs retain 41 events and 24 ending positions. Full replay captures are
retained; old and current result/state/ledger hashes remain distinct.

The three original golden assertions were deliberately run with `--runxfail`:
all three still fail against the obsolete reference. The measurement assertion
fails before measurement executes. This does not demonstrate nondeterminism or
measurement mutation. No golden or xfail was changed and no new compatibility
reference was approved.

**Corrected champion history remains data-dependent.** Missing inputs are the
complete authenticated Sharadar SEP history, SFP SPY/BIL benchmark history,
ACTIONS/terminal terms, dated TICKERS/issuer/exchange/alias authority, and the
matching manifest/publication/rejection provenance for the selected historical
window and warmup. The retained research tape/dataset digest
`5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
does not substitute for those production inputs. No matching complete raw
corpus is available in the inspected checkout. Snapshot TICKERS without dated
effective history is insufficient for a point-in-time claim.

When those inputs are provided: hash and inventory them; validate domains,
coverage, actions and dated identities; pin one read-only publication; drive
`production_strategy`, `warm_session_state` and `advance_session` in session
order through the measurement window. Retain every input/state/ledger hash and
controller decision, with scheduled JSON/process restarts. Compare against
the prior implementation on the **same** inputs, decompose share/cash/action/
terminal/cooldown/exposure deltas, and independently sum economic events.
Decision-at-close versus effective-next-open alignment must be explicit.
Do not use `tools/sentinel_forward_chain.py` as a compact-champion certificate:
it pins the older Sentinel 1.1 rule/reference. A corrected-profile replay driver
and reviewed economic reference are still required; inventing metrics without
the corpus would hide that gap.

## Concrete NAS handoff (not executed here)

1. Before NAS qualification, resolve or explicitly review the code/provider/data
   blockers above, merge through owner review, and require successful CI for
   the exact accepted commit. Record source SHA, image digest, configuration
   digest, strategy economic schema and accepted capability evidence. Preserve
   all previous failed GO attempts. No earlier certificate transfers to /2.
2. Authorized operator first records read-only inventory: `git rev-parse HEAD`,
   `git status --short`, `docker ps --format '{{.Names}} {{.Image}} {{.Status}}'`,
   and `docker image inspect <reviewed-image> --format '{{.Id}}'`. Run
   `bash scripts/sentinel-backup-status.sh` under the reviewed maintenance
   environment. Retain sanitized output; do not dump credential environments.
   **Fail** on source/image mismatch, missing failed-attempt history, missing
   backup/WAL identity, mixed runtime or an unexplained authority generation.
3. On an isolated restored database, using the exact accepted runtime and no
   broker credentials/network, run `python -m sentinel.restore_validation` with
   `SENTINEL_DATABASE_URL` pointing only to that clone. Run the retained local
   acceptance commands below under the reviewed test image. **Pass** requires
   read-only semantic validation, rolling origin/current checkpoint/shadow and
   action closure, exact cash/fill/command reconstruction, and refusal of each
   corrupted fixture. A structural pass grants neither GO nor broker authority.
4. With separate operator authorization, run
   `bash scripts/sentinel-restore-drill.sh --backup <completed-base-path>`.
   This creates a disposable restore and appends a proof after success; it is
   not a purely read-only primary operation. Retain base manifest, system ID,
   timeline, marker/XID/LSN, WAL checksums, replay target, semantic report and
   final backup proof. **Fail** on any missing segment, wrong branch/target,
   changed economic state, retained-history loss or absent current snapshot.
   Physical-only success cannot satisfy semantic qualification.
5. Run the accepted full corpus replay on an isolated copy as specified above.
   Inventory exported raw inputs with
   `python scripts/sentinel-corpus-inventory.py --sharadar <export-root> --deep --out <new-evidence>/corpus.json`.
   **Pass** requires complete causal input authority and independently explained
   deltas; no unexplained mismatch, hidden xfail or golden rewrite is acceptable.
6. Only after provider contracts and a separately approved paper-account test
   plan exist, qualify cash/fill/backfill/correction/request and predecessor
   histories on the exact intended provider surface. Retain native IDs, query
   boundaries, account binding, complete pages/cursors, execution/publication
   clocks, endpoint observations and rejected contradictions. **Fail** if empty
   reads, elapsed time or test-only capability switches supply finality.
7. Qualify restart/reboot, prolonged source/database outage, missing sessions,
   full log/storage/backpressure, lease/generation takeover, backup rollover,
   retention and real-device push/rotation on the target topology. Retain
   bounded completion times, memory/disk peaks and each durable transition.
   **Fail** on abandoned uncertain commands, replacement transport, lost alerts,
   incomplete restore or violation of the documented operational budgets.

The operator must keep provider acceptance, replay compatibility, physical
restore and unattended runtime qualification as separate verdicts. Issue 399
remains open until every required gate has affirmative, reviewed evidence.

## Local execution record

Reviewed code commit: `c1c4519c444c79ac6852968e415feca79b5f22bf`.
Physical restore and six lifecycle scenarios used clean cloned commit
`354a431a053886d2267438997d167ce79901d881`; the following code commit changes
the unaccepted candidate SSE path and its tests, not those modeled scenarios.
The final delivery commit additionally retains this report/evidence. No tests
are represented as having run on a later code revision than they did.

The original GitHub head `97a5fb45` finished all six workflows successfully:
Sentinel safety, Alpaca simulation, operator browser, production composition,
backup reliability and internal state. That result does not transfer to the
new commits; GitHub must validate the final PR head independently.

Runtime: Python 3.12.13, psycopg 3.3.4, isolated PostgreSQL 17.11, image
`sentinel-test:ci` with local ID
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`.
Every container used `--network none`, a read-only repository mount and an empty
`.env` overlay. PostgreSQL ran in disposable container storage. PostgreSQL 16
and the exact NAS image remain target qualification; these are not claimed by
the local PostgreSQL 17 results.

| Campaign / exact runner invocation inside the isolated container | Result |
|---|---|
| `python /evidence/run_campaign.py acceptance` | 116 passed, 1 fixture failure: the new empty-restore test inherited a DDL monkeypatch inside a read-only transaction. Restore the production schema guard in that test; rerun below passed all four restore cases. No production contract was relaxed. |
| `python /evidence/run_campaign.py restore-push` | 5 passed: four restore cases plus HTTP-response takeover fencing. Together with the preceding run, all 117 acceptance cases pass; there was no single 117-green rerun. |
| `python /evidence/run_campaign.py regression` | 375 passed, including ownership, journal/reconciliation, automation, restore and provider boundaries. |
| `python /evidence/run_campaign.py strategy` | 339 passed: champion, median5, V5, changed economic boundaries and the relevant Wealth Core state machine. The full Wealth Core suite was not run. |
| `python /evidence/run_campaign.py cash-crash` | 21 passed, STRICT_V1 and retained real SIGKILL transaction-boundary probes. Inputs explicitly model an accepted cash contract; no production producer is promoted. |
| `python /evidence/run_campaign.py predecessor` | 4 passed across fresh-process strict predecessor and restore-upgrade fencing. |
| `python /evidence/run_campaign.py sse-wire` | 88 passed; snapshot replay mutation killed. |
| `python /evidence/replay_golden.py` | Both immutable-source replays captured; 6 independent reconciliation tests passed. |
| `python /evidence/run_campaign.py golden-unmasked` | 3 expected failures with `--runxfail`, proving the obsolete reference still differs. These are unresolved reference gates, not green tests. |
| `python /evidence/clean_replay.py physical` | 2 passed: actual base backup, WAL replay/promotion, before/after-retirement table fingerprints and rolling closure, on clean `354a431a`. |
| `python /evidence/clean_replay.py lifecycle` | All 6 modeled PAPER/LIVE_CASH scenarios passed on clean `354a431a`: populated lifecycle, death after submit acceptance, and partial-fill/cancel race. `LIVE_CASH` here is a simulator profile, not a real account. |
| `python tools/v5_mutation_check.py` / `python tools/champion_mutation_check.py` | 43 / 4 mutants killed. |
| `python tools/economic_audit_mutation_check.py GUARD` | All 8 guards killed: `fills`, `coverage`, `attempt`, `durable-fills`, `terminal-split`, `restore-origin`, `push-attempt`, `snapshot-replay`. Passing baselines precede each mutation. |
| `python /evidence/check_source.py` | All 80 PR-changed Python files compile; 0 introduced pyflakes findings against `97a5fb45` (104 existing findings). |
| `python tools/validate_test_responsibility.py --base aff4461d9af6d4a7367018768fda18d948958b49` | PASS; 464 test modules, no unowned modules or added incident-named tests. |
| `git diff --check` and `git diff aff4461d9af6d4a7367018768fda18d948958b49 HEAD --check` | Passed. |

Counts overlap and must not be added into a unique coverage number. The earlier
172-case focused pass and intentional red probes remain in the archive. Also
retained are unsuccessful harness attempts: missing subprocess schema, a
non-traversable temporary directory for PostgreSQL WAL archiving, and a missing
test-only receipt key. Correcting those fixture conditions yielded the explicit
passing reruns above. An initial terminal mutation exposed a cached test alias;
the test now calls through the patched module and kills the mutation. The first
push mutation baseline had a wrong SQL column in the new test; after correcting
it, both the passing baseline and killed mutation were retained. None of these
failed attempts is counted as acceptance evidence.

The [evidence package and exact reproduction instructions](../audit/economic_399/pre_nas_402/README.md)
retain command argument arrays, stdout, JUnit XML, replay captures, lifecycle
reports/traces/provider transcripts, source provenance and per-file SHA256.
Historical retained test inputs are tied to immutable audit commit
`ec9623070908b437222b2e1d963d3ceb8721f9bb`. No old artifact was overwritten.
