# P01 grouped factual stopped review

The accounting and stopped-review helpers consume only the new committed suffix
after admitted OWN526. The old admission and its canonical restore/accounting
proofs are reused. Historical source515 checkpoints remain immutable gzip
lineage; they are not decoded using source516. Current source516 and all ten
archived codecs plus the approved historical quote are hydrated before any
Ledger or SessionState restore. The ordinary eleventh input is loaded separately
and in order. No reviewer input can create a new source boundary.

`p01_factual_batch_accounting.reconcile(snapshot, quote, actions=None,
ordinary=None)` runs the existing independent raw cash/share/receivable/NAV
equations and the unchanged historical CELG rights proof, then checks any grouped
action ledger events against the exact dated legal registry. Cash consideration
is distinct from quotes. Unsupported fractions, wrong clocks, source-held use of
unheld-only terms and extra payments refuse; no rounded cash or invented quote
is introduced. Canonical cash/stock ledger representations remain authoritative
and their exact arithmetic is audited independently.
For stock-plus-cash postings the check reproduces the frozen holder cumulative
cash allocation and subsequent binary64 subtraction exactly. The ledger detail
uses the frozen `round(allocation.cash_leg, 10)` presentation, which is distinct
from the posting delta. A binade-crossing subtraction can differ from the ideal
legal cash component; this is checked by operation equality, without tolerance
or a new financial rounding rule. The ideal legal amount remains separately
recorded as a rational value.

`p01_factual_batch_review.review(spec, out, evidence)` is hosted-only and writes
`out/factual-batch-financial-review.json`. Original parent evidence is `/old`.
The reviewer verifies the epoch checkpoint is exactly OWN526 and checks actual
watch prefixes and source-event counts, rather than trusting a zero counter.
Only one new input-successor event is permitted. Qualifier and fresh-finance
zero boundaries and first two full state hashes/roles must agree. All original
checkpoint gzip files, old input bytes and committed prefixes remain exact.

Every new input-zero, current, pre-event and month-end checkpoint receives the
canonical new-epoch restore check and journal-prefix verification. New raw
accounting snapshots, funded factors/chains, correlation bindings, monthly
reporting state and retry counters are reviewed over the exact committed axis.
The actual pre-event checkpoint supplies full prior roles for each registered
action. Existing unheld native scopes remain checked against prior holdings and
all pending orders; target holdings are not gratuitously excluded. An unheld
source may coexist with separately qualified target holdings or target orders.
A held source with a held target requires its own full-state component proof;
a held source with any target pending order remains unsupported and refuses.
The stopped reviewer reads those actual component wires, verifies their source
map and exact parent-policy configuration, compares the complete target control
states, checks the four stock postings and preserved target episodes, and
roundtrips the serialized full SessionStates using the authenticated source516.
It does not rerun synthetic transitions or choose a default slot policy.
An integral holder entitlement may have exact binary fractional episode
allocations; per-episode whole shares are not imposed. Initial reference
representations and the canonical final residual allocation must still be exact.

A partial or refused branch is reviewed only through its actual committed
checkpoint, with current tails retained and no inferred completion. The segment
is complete only at June 29, 2020 with 101 new transitions and 627 total closes.
The complete attempted role, component, action and inherited-scope records remain
encrypted evidence. Each committed list must equal the entire attempted list
filtered at the saved cursor. Uncommitted attempts may concern only the next
session; their available full-state and pre-event bindings are checked separately
and cannot be counted as a committed transition. All logged pre-event archives,
including the refusal day, receive canonical restore and prefix verification.
The frozen journal writer uses the same strict JSON, empty gzip filename,
mtime zero and compression level one for both archive and current. Accordingly
each logged current-file byte length and hash must equal the actual retained
pre-event gzip bytes, in addition to the complete logical mapping checks.
The reviewer never admits a financial predecessor; root retains that authority.
All local tests are arithmetic, metadata and stub/falsifier tests. No local
canonical strategy/controller/account replay is performed.
