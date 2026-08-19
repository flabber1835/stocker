# Sharadar financial-grade authority closure

**Status:** review branch follow-up to merged PR #186, 2026-08-19.

This note records the post-#186 audit findings that required additional source
authority. It does not change Wealth Core or Sentinel strategy rules.

## Economic domains

The corrected liquidity contract remains:

```text
raw_compatible_volume = SEP.volume * SEP.close / SEP.closeunadj
SEP.closeunadj * raw_compatible_volume == SEP.close * SEP.volume
```

`sentinel_bars.volume` and post-fix `bt_prices.volume` therefore store the
raw/as-traded-compatible quantity consumed with the raw close, not the verbatim
Sharadar source volume.

The corrected dividend contract remains:

```text
raw_dividend_per_share = ACTIONS.value * SEP.closeunadj / SEP.close
```

A positive dividend without both price domains fails closed.

## Whole-export negative-space authority

Two identical cursor-paginated reads prove stability, not completeness. The same
prematurely terminal response could repeat. Nasdaq Data Link's documented Table
Exporter provides a stronger witness for the cases where absence itself changes
economics: a generated zipped CSV plus `file.status`,
`file.data_snapshot_time`, and `datatable.last_refreshed_time`.

Sentinel accepts an export only when it is `Fresh` and its snapshot creation time
is at or after the table's latest refresh. Credential-bearing download URLs are
transport-only and are not persisted or rendered.

Official provider reference:

- https://docs.data.nasdaq.com/docs/in-depth-usage-1

## TICKERS and daily SEP

TICKERS field values remain on strict paginated JSON because source NULL and an
observed blank `relatedtickers` carry different semantics. The fresh whole-table
export is used only as an independent `table=SEP` `(permaticker,ticker)` key-set
witness; the paginated and exported key sets must match exactly.

For every newly exposed SEP session, those same stable TICKERS listing intervals
predict the expected priced ticker population. Observed SEP coverage must be at
least 99.9%. Retained 2026 calibration found the worst legitimate coverage at
about 99.9518%; the large 2026-07-31 to 2026-08-03 population contraction was
fully explained by TICKERS listing ends.

This makes the older 80% recent-population readiness threshold an anomaly check,
not publication-completeness authority.

## ACTIONS

A missing ACTIONS row can erase a split, dividend, or terminal event. Production
complete reconciliation therefore uses a fresh whole-table export over the
explicit `1900-01-01..decision-frontier` window. The stronger durable cursor is:

```text
sharadar-actions-export-reconcile:v2
```

A legacy v1 cursor cannot satisfy v2 readiness. The default complete-export
cadence is one decision day. Split/dividend changes re-normalize the affected SEP
windows against the candidate action generation before one publication activates
both action and bar economics.

## Historical TICKERS identity correction

`sentinel_bars` is keyed by `(security_id,session)`. Publishing only a corrected
TICKERS interval can leave an old historical bar key visible under a resolver
that no longer names it. A complete TICKERS candidate is therefore refused if it
changes, introduces, or omits a listing interval overlapping already-published
SEP history.

Forward-only daily interval extension and genuinely new post-frontier listings
remain allowed. A real historical identity correction needs a complete
identity-aware rebuild capable of re-keying/tombstoning affected bars atomically;
the runtime does not guess that repair.

## Recent SEP deletion/key proof

`lastupdated` finds changed/inserted SEP rows but cannot reveal a row that vanished.
The rotating annual audit remains useful for deep history, but the current Wealth
Core signal window receives an additional proof every daily cycle.

After ordinary daily publication, SEP mutation CDC, and complete ACTIONS
reconciliation all finish, Sentinel exports and canonically reconciles the exact
`REQUIRED_CLOSES` decision-history window. It compares:

1. normalized `(security_id,session,ticker)` membership; and
2. exact persisted signal close, raw close, raw open, and volume.

The dedicated recent-proof cursor names both the decision frontier and the exact
current corpus publication version. Readiness fails if the proof is missing,
behind, or belongs to an older publication. Any later mutation publication thus
invalidates an earlier negative-space proof automatically.

## Existing bt_prices migration

A pre-#185 `bt_prices.volume` column contains the old split-adjusted source
quantity, while new rows contain raw-compatible volume. Numeric values cannot
identify which semantic epoch produced an existing row.

The schema therefore adds a nullable `volume_domain_version` with **no default**
and one singleton `bt_price_volume_domain_state`. **Every database starts
`proven=false`, including a fresh empty one.** That is intentional: bt-data's
runtime bootstrap applies DDL statement-by-statement, so a later failure creating
the write trigger cannot leave an earlier `proven=true` authority row behind.
Only the explicit migration command may establish the semantic verdict.

Only the post-fix bt-data process may stamp a price row:

```text
sharadar-raw-volume-v1
```

The process injects `application_name=bt-data-sharadar-raw-volume-v1` through
asyncpg's documented `server_settings` connection argument. The trigger accepts
that exact writer identity. A rolled-back/undeclared bt-data binary clears the
row marker and invalidates the semantic singleton **in the same transaction as
its first price write**. Thus old application code cannot silently keep a prior
financial-grade verdict after changing the corpus.

The bt-engine READY-generation gate checks the singleton in O(1) time before its
first price read. This is explicit rather than row-level security because the
existing backtest PostgreSQL bootstrap role is a superuser and can bypass RLS.
It also avoids building a lifetime-sized index over ~35M legacy rows merely to
say the old corpus is unproven.

The supported one-time repair is the resumable command inside the post-fix
bt-data image:

```text
python -m app.volume_domain_migration
```

It owns the normal corpus writer lock and resumes **only its own** interrupted
`VOLUME_DOMAIN_MIGRATION:v1` PUBLISHING generation. It first verifies that the
entire semantic schema, including the trigger, installed successfully. For a
populated corpus it then force-replays the complete stored SEP date range and
refreshes configured benchmark prices. For an empty corpus the proof is trivial,
but still explicit through the same command.

For a populated corpus, once per migration, the command performs the expensive
acceptance scan and proves there are zero rows whose `volume_domain_version`
differs from `sharadar-raw-volume-v1`.

Only after that residual proof succeeds does the migration stage
`bt_price_volume_domain_state.proven=true`; the semantic verdict and new READY
data UUID commit together through the same publication transaction. A crash
before that commit leaves the previous unproven state intact and the migration
resumable.

An old row absent from current source is neither deleted nor grandfathered. It
remains unmarked and blocks migration completion until the source/key
disagreement is investigated.

The existing `POST /jobs/backfill-prices` endpoint remains the underlying force
replay primitive, but the migration command is the supported upgrade because it
also refreshes benchmark rows, proves zero residual legacy semantics, handles
restart state, and publishes READY only after the complete proof succeeds.

`bt-engine` starts only after bt-data health establishes the semantic schema, and
its READY generation read independently requires the proven singleton in the same
corpus snapshot used to identify the generation.

## Final authority shape

```text
strict transport/protocol
    -> TICKERS whole-export identity-key witness
    -> repeated cross-table source stability
    -> SEP listing-population completeness
    -> canonical economic normalization
    -> durable candidate + publication
    -> SEP lastupdated CDC
    -> ACTIONS daily whole-export reconciliation
    -> recent SEP whole-export key/value reconciliation
    -> readiness bound to exact final corpus version
```

This proves consistency with the current Sharadar reconstruction. It does not
recreate historical vendor vintages that were never retained and does not alter
the separately documented point-in-time SEC/certification limitations.
