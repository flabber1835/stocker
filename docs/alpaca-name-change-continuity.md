# Alpaca asset recreation on a non-economic name change

Decision: 2026-10-12. Alpaca documents that a CUSIP name change retires the
provider asset object and creates another object. A provider UUID is therefore
not a permanent economic identity across this event. The observed Monday
refusal retained an unheld leadership constituent under its Friday identity;
the new inventory had another UUID for the same symbol, and the candidate-only
action reset removed the price needed for its return. The refusal preserved the
book and sent no commands.

Provider contract:
<https://docs.alpaca.markets/us/docs/mandatory-corporate-actions>.
Name changes update symbol/CUSIP identifiers; they are distinct from splits,
mergers and reorganizations. Unit splits distribute common stock and warrants
from a unit; an existing holder of the delivered common stock is not splitting
their holding.

## Identity ownership

Preserve the canonical security identity already admitted in the preceding
operational snapshot. Record the current provider UUID separately in the new
reference evidence. Broker instrument discovery continues to resolve the
current symbol and independently retain the current broker UUID through the
existing execution membrane. No broker position, activity or order is an input
to this identity decision.

Initially support same-symbol, changed-CUSIP name changes only. Bind continuity
to one complete, dated provider `name_changes` record, one prior ordinary-equity
listing, and one current classified ordinary-equity listing. Both CUSIPs must
be present and distinct, the event must follow the preceding source frontier,
and prior/current symbols must agree. A changed UUID without this evidence,
duplicate or conflicting name changes, a reused mapping, changed symbol,
economic source-side action, ambiguous identity or missing usable prices remains
a refusal/pending input. A display-name similarity or equal historical price
alone cannot establish identity.

Persist the provider-to-canonical identity binding and the original event
evidence in the immutable reference/source evidence. A following snapshot may
reuse the authenticated binding for the same current provider UUID; it must
not infer another continuity step from a familiar symbol. Existing snapshots
and book records are immutable and are not re-keyed or replayed.
The retained action-part generation binds the authenticated predecessor identity
inventory. Same-day reacquisition reuses a valid new-schema binding; an older
same-day publication that failed continuation cannot replace the preceding
dated identity evidence.

Name-change continuity has no share conversion ratio and changes no share count,
cash, entry, peak or controller membership. The actual current price earns the
ordinary return for the retained leadership member. Missing prices never earn
a fabricated zero/flat return, and the unresolved-return guard remains intact.

## Action participants

For a unit split, distinguish the unit being split from its delivered securities.
Reset/quarantine the source unit by its source symbol; do not reset an existing
common-stock series merely because it is named as delivered consideration.
Keep unsupported economic events for a source common-stock holder unavailable;
this change does not introduce unit ownership, merger settlement or guessed
corporate-action terms. Conflicting source-side actions prevent name-change
continuity.

## Publication and executable admission

The new source/reference identity requires fresh ordinary source
acquisition and publication. Older authenticated input schemas remain readable
for the retained origin and prior-state checks, but cannot satisfy new source
readiness. Preserve all historical observations and original validity clocks.
The raw and split-adjusted price normalization policy is unchanged.
Version 2 source evidence and version 3 references must occur together; their
identity-binding digest must agree. Historical version 1 source evidence keeps
its older reference schema. A mixed or missing binding is refused by the reader.
The executable upgrade profile must pin exact reviewed predecessor bytes and
the new adapter/reader targets. Unknown source edits remain refused.

Software installation, financial GO, restoration, unsent-cycle authorization,
paper kill release and transport retain their existing certified sequence.
There is no alternate book, provider fallback, manual order or authority bypass.

## Qualification

Use generic renamed fixtures for same-symbol CUSIP/UUID replacement, ordinary
unchanged inventory, repeated daily binding reuse, inbound unit delivery,
source unit quarantine, held-state continuity, the retained leadership return,
restart and lost reply. Refuse absent/duplicate/future/conflicting events,
unsupported economic source actions and an unproven UUID replacement. Mutate
the binding/action guards and verify the falsifiers fail. Verify historical
schemas remain readable and fresh source readiness requires the new schema.

Before publication, run the actual GET-only provider inputs and retained public
source identities through an in-place read-only adapter check. Combine that
with isolated PostgreSQL canonical held/leadership, daily continuation and restart
fixtures. Independently verify original book/binding and failed-cycle records
before and after the source diagnostic. Do not export private account records
or claim that this scoped adapter proof is a financial GO certificate.
Then require green protected CI, certified image publication, supported
installation, full financial GO/restore and exact Tuesday prospective-cycle
verification before operational completion.

The observed input check on 2026-10-13 kept all 5,913 classified source
listings and admitted one source-bound same-symbol name-change binding.
The retained raw/signal anchor was $17.09 and the actual next raw/signal close
was $16.91, an ordinary price return of approximately -1.05325%. The earlier
2025-10-30 history reset remained in force. The check made no database or broker
mutation, copied no production book, and created no database dump or clone.
