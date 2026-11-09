# Producer-owned calendar bounds for shadow health

Selected root correction: a disposable health process must not rebuild the
1997–2100 XNYS calendar to judge an already authenticated shadow projection.
The measured cold-calendar work and naturally captured CPU-throttled observer
timeout justify removing this work. They do not establish the initiating cause
of the historical ARM or leader-loss incidents.

The existing canonical verifier remains the only publisher of this health hint,
under its writer lock and after full verification. It resolves calendar facts
using the unchanged pinned calendar implementation and publishes projection
schema 2 with these authenticated fields:

- Session S and the immediately following exchange session N.
- `valid_from`: the actual close of S.
- `current_until`: the actual close of N.
- `valid_until`: the actual open of the exchange session following N.
- The calendar implementation identity.

The consumer retains the fresh database inventory, configuration, size, schema,
HMAC and original record/authority bindings. It interprets UTC time as follows:

| Time | Health result |
|---|---|
| Before the close of S | Refuse a future projection |
| Close of S through just before close of N | HEALTHY_ATTESTED, target S |
| Close of N through just before following session open | HEALTHY_WAITING, target N |
| At or after following session open | Refuse missed causal boundary |

These are exactly the existing one-missed-close semantics, including holidays,
half-days, weekends and daylight-saving changes. No TTL, lease, trading window,
broker admission or financial verification changes. No new calendar logic is
inferred from calendar dates or from the input corpus. A reversed, naive or
non-UTC interval refuses. The lower time fence is required even for an otherwise
correctly signed payload.

Schema 1 hints fail closed under the new reader and are replaced only by the
normal verified producer. They are auxiliary health evidence, not financial
history; historical financial receipts and frozen economic modules are unchanged.
There is no legacy fallback that silently restores heavy calendar work on every
probe. A rollback similarly needs its ordinary fresh producer hint.

The health reader performs datetime comparisons only and must not load pandas,
NumPy or exchange_calendars. Producer work is reused from its already warmed
calendar process. Existing bounded file publication and failed-write behavior
remain unchanged: a failed hint write cannot alter the canonical book.

Qualification compares new eligibility to the unchanged original calendar at
each boundary, with holiday/DST/half-day cases, rejects changed inventory/HMAC
and future/expired hints, proves a cold reader loads no heavy calendar modules,
and includes a falsifier for a removed lower time fence. No economic manifest
or old financial fixture is repinned.
