# Coherent feed recovery acquisition

## Incident and scope

NAS validation of `388b8652` failed on 2026-09-07. The first seed refused 131
historical listing changes after 32 seconds. Identity recovery then spent
42 minutes in a seed before ACTIONS corroboration found 698,014 versus 697,996
rows. Preparation as a whole took about 68 minutes. These observations establish
source disagreement, not its cause. The prior failures also include TICKERS
instability, SEP coverage refusal and trailing-key mismatch.

The recovery branch changes feed acquisition, recovery sequencing and diagnostic
evidence. Median-5 PR #333 owns strategy promotion independently.

## Acquisition contract

Production seed captures all required source inputs to private temporary files
before normalization or candidate row writes. Existing SEP canonical, duplicate,
session, update-ceiling, repeated-observation and exact listing coverage guards
validate those files. Reference corroboration brackets source acquisition;
database replay time is outside that bracket. A failed capture closes its files
and never starts a seed candidate. Every new invocation obtains fresh authority.

ACTIONS uses the existing complete filtered Nasdaq Tables Exporter contract.
One fresh file supplies its rows. A second status request after SEP acquisition
must still report a fresh export, snapshot time at or after table refresh, and
the same table refresh as acquisition. Replaying the file is not a second
independent content observation: the independent corroboration is vendor refresh
metadata. Changed or unavailable refresh evidence refuses before replay. The
request interval is exact, rows are date-validated, and existing empty/mass-shrink
guards remain mandatory. The final complete ACTIONS reconciliation remains in
the seed publication workflow.

TICKERS retains paginated JSON field semantics, whole-export key completeness,
and independent content corroboration. CSV does not replace NULL-versus-empty
metadata authority. SEP and SFP retain their existing stability checks. The
post-seed mutation and trailing-source proof remains live and mandatory; capture
does not grant freshness to a long-running database replay.

## Recovery sequencing

The captured candidate TICKERS rows undergo the existing historical-identity
guard before a durable seed run is opened. A named HistoricalIdentityMutation
selects the existing complete identity-aware rebuild, its coverage checks and
atomic finalizer. Other failures propagate. This avoids an intentionally failed
seed and duplicate source acquisition. Failed-owner recovery and the corpus
writer lock remain in force. Captured rows cannot authorize requests outside
their exact request keys.

## Diagnostics and validation

Structured progress identifies source capture, ACTIONS refresh checks, identity
rebuild selection, database chunks and post-seed proof, with monotonic elapsed
time and row counts. Only a closed, sanitized event schema is printed by the NAS
wrapper and retained in preparation diagnostics in the review ZIP. URLs,
credentials, arbitrary exception messages and raw vendor rows are excluded.
Failure summaries distinguish failed preparation from unexecuted work.

Regressions must prove refresh drift refuses before candidate mutation, capture
failure closes all files, identity recovery reuses captured source, failed
publication retains authority guards, and unsafe progress data is rejected.
CI establishes code behavior. A later NAS run establishes actual preparation
time; no speed claim is certified by simulated timing.

Vendor contract: [Nasdaq Tables usage](https://docs.data.nasdaq.com/docs/in-depth-usage-1).
