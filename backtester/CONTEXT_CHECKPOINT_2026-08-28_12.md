# Backtester context checkpoint 12 — 2026-08-28/29

## Immutable production boundary

Production/main remains untouched by this research. The strategy source under test is pinned read-only at:

`c502d077cae9c494f8b74a41ee8be7f40b25837d`

## Checkpoint/resume certification

The first checkpoint/resume equivalence is now GREEN:

- workflow run: `33230325743`
- uninterrupted window: 1998-01-02 through 1998-06-30
- checkpoint: 1998-03-31
- resume begins: 1998-04-01
- uninterrupted and resumed `daily.csv.gz`, `metrics.csv`, and `summary.json` are byte-identical after canonical daily-column serialization was installed.

The previous red run `33228577567` had exact semantic/numeric equality and failed solely because JSON `sort_keys=True` reordered keys in retained daily-row dictionaries. That serialization issue is fixed by:

- `backtester/checkpoint_output_schema.py`
- `backtester/run_checkpoint_equivalence_base_v2.py`
- `backtester/run_sector_ad_v3_checkpointable_v2.py`

A stronger stateful equivalence workflow has been launched:

- `.github/workflows/backtester-checkpoint-resume-stateful-equivalence.yml`
- commit `83cbf8de2350b9af59e1800ea296a2f21d130227`
- uninterrupted end: 1999-06-30
- checkpoint: 1998-12-31
- acceptance additionally requires a nontrivial/live Wealth Core portfolio at the checkpoint.

## 2007 unresolved-open blocker: EFD1 repaired

Old A/D v2 run `33210946520` reached 2007-07-11 with:

- A multiple = 5.8454889361
- D multiple = 5.8454889361
- A/D cumulative CAGR from 1998-01-02 = 20.3790533354%

It then failed on an unresolved Wealth Core open coinciding with an allocation transition.

The comprehensive six-hour scanner artifact identified the blocker:

- ticker: `EFD1`
- security ID: `182962`
- unresolved/collision session: `2007-09-13`

Primary-source terms:

- eFunds was acquired by Fidelity National Information Services.
- merger consideration: $36.50 cash per eFunds common share.
- acquisition completed: 2007-09-12.
- consideration was publicly fixed by 2007-06-27.

The frozen terminal bundle now contains EFD1:

- security_id: `182962`
- ticker: `EFD1`
- kind: `CASH_MERGER`
- effective_session: `2007-09-12`
- known_by: `2007-06-27`
- cash_per_share: `36.50`

Current terminal bundle SHA-256:

`793b70aee5f074f8fb0640371242c6e35952956ce040f187b14a81d355f13da6`

Verification:

- causal terminal terms run `33230738054`: SUCCESS
- production terminal integration run `33230759612`: SUCCESS
- integration proves a held EFD position is extinguished and receives exactly $36.50/share with CASH_MERGER ledger semantics.

## Split audit: seven direct primary-source adjudications

Original full-corpus unresolved split count: 128.

Direct primary-source adjudications now frozen for:

1. ACER 2017 — 0.09656678988910945
2. GOLLQ 2017 — 2.5
3. MTL 2008 — 3.0
4. MTL 2016 — 0.5
5. ONSM 2003 — 1/15
6. PTIX 2016 — 1/15,463.7183
7. SQNS 2019 — 0.25

Current direct split dataset SHA-256:

`95e6c4f9519d70f88a3f4f17fccfb9bc6df772989b14210bd801a3d2e2c22557`

Exact-event frozen-main verification:

- run `33230648632`: SUCCESS
- all seven events preserve the original Sharadar stated value and SEP-derived witness and apply the legal primary-source multiplier with the distinct adjudicated disposition.

Full 46,238,394-bar audit:

- run `33230668663`: in progress at this checkpoint
- hard expected result: 7 adjudicated, unresolved 128 -> 121, final session 2026-07-31.

## Four remaining genuine split date/domain anomalies

The remaining genuine conflicts are not safe direct same-session overrides:

- DAYR 1998
- PRTK 2009
- NEOM 2014
- PRPO 2017

Known legal evidence:

- DAYR: 2-for-1 approved by shareholders 1998-03-18; additional shares distributed 1998-03-30. Sharadar shows a 10x adjustment-domain transition on 1998-03-18, so the vendor adjustment date/magnitude does not represent the legal share event.
- PRTK: Novacea/Transcept transaction included a 1-for-5 reverse split on 2009-01-30; post-transaction TSPT trading began 2009-02-02. Sharadar conflict is keyed 2009-02-06 with a 2.4x domain transition.
- NEOM: primary filing documents a 1-for-15 reverse split effective 2014-05-11; Sharadar conflict is keyed 2014-05-29 and derives about 1/14 amid mill-priced adjustment noise.
- PRPO: Transgenomic 1-for-30 reverse split effective 2017-06-13. Sharadar shows approximately 1/450 on 2017-06-06 and approximately 15x on 2017-06-30; their product is 1/30.

Focused frozen-data diagnostic:

- script: `backtester/diagnostics/inspect_split_date_domain_anomalies.py`
- workflow: `.github/workflows/backtester-inspect-split-date-domain-anomalies.yml`
- run `33231088275`: in progress at this checkpoint

It records exact raw/signal SEP rows, raw price moves, adjustment-factor transitions, permanent security IDs and ACTIONS rows around all four events.

Do not encode these four as simple direct overrides. The repair must apply the legal multiplier on the legal/effective trading session and suppress only specifically witnessed stale/misdated vendor adjustment transitions.

## Checkpointed comprehensive terminal-gap scan

The original single-job held-terminal scan hit GitHub's six-hour ceiling but uploaded partial evidence. It captured many held unresolved terminal gaps and identified EFD1 as the 2007 allocation-collision blocker.

Checkpointed full scan is launched:

- root run `33230785210`
- segment 1 is in progress at this checkpoint
- immutable research SHA for that launch: `9826dde7ee3c0beb40d04ffb6b94250f4c63f59f`
- scanner carries accumulated gap episodes inside the hashed checkpoint between segments.

The final scan must enumerate all held unresolved terminal episodes across 1998-2026 after current terminal/split repairs.

## Current continuation order

1. Consume run `33231088275` and classify exact legal-vs-vendor sessions for DAYR/PRTK/NEOM/PRPO.
2. Implement a separate causal date/domain split-adjudication dataset and loader; keep it distinct from direct same-session overrides.
3. Verify each date/domain event on frozen-main normalization.
4. Run full 46.2M-bar audit with all direct + date/domain adjudications.
5. Consume checkpointed terminal-gap scan segments and research every economically active held terminal gap.
6. Require stateful checkpoint equivalence green.
7. Run final checkpointed v3 A/D chronology only after terminal/split integrity gates close.
8. Publish CAGR/Sharpe/DD/SPY results only from that final complete causal/PIT economic replay.
