# P01 IAC unit guard interface recovery

The first IAC unit qualification stopped with an authenticated Python interface
failure before either financial transition. Published run 41444401941 at
83cbeccae07b5cfdbe54420e9318142761b3b303 and its encrypted partial qualification
remain immutable. Its guard accessed `backtest.Buffer`; the exact admitted 516
source imports the `research.pooled_input_support.adapter` module and constructs
`adapter.Buffer()` inside `backtest.run_backtest`. The class itself is absent from the backtest
module's globals. This is a research driver interface defect, not an input,
market, strategy, source epoch, financial state or legal-unit change.

The recovery uses new files and a new selected request. It starts from original
admitted own628, hydrates the same eleven archived inputs and quote, performs the
same unchanged source zero and exact twelfth-input zero, then requires the same
two-session full reference/FAST qualification and separate fresh finance. The
public input bytes, facts, predecessor, 516 financial sources, 224 canonical
sources, scalar operation order, endpoint and every financial/action guard stay
bound to the published request. The old 484 driver blobs and failed evidence are
retained, never overwritten or labelled a successful qualification.

`p01_iac_unit_recovery_guard.py` subclasses the frozen guard and replaces only
context entry/exit. Before installing a hook it verifies the complete actual
backtest and adapter module hashes against the admitted source map, statically
checks the module-level adapter import and exact class construction in `run_backtest`, and
selects `research.pooled_input_support.adapter.Buffer`. It does not add an alias
to backtest or alter canonical source. It installs the unchanged base action
guard and then patches that exact adapter class's `prepare`. On normal exit,
body failure or recovery setup failure after the frozen base context has been
established, it restores every installed hook. The frozen base context's own
entry lifecycle is unchanged; this recovery makes no new partial-entry guarantee
for that old function. A nested or
unexpected class/method identity refuses.

`p01_iac_unit_recovery_run.py` reuses explicitly source-pinned frozen driver
functions with only the `UnitGuard` global binding and the economic host-gate
module changed to the new recovery namespace. Function bodies, source/input
boundary construction, feature/reference operations, accounting and qualification
records remain unchanged. The new host must select this entrypoint and bind the
same input hash and source closure; no synthetic environment flag authorizes
financial state. No qualifier checkpoint is adopted.

The recovery entrypoint selects the exact read-only `/driver` request path.
Its first I/O validates that whole raw request and the complete source closure
through the recovery job's metadata-only request validator. Only then
does it import the frozen runtime module or enter any original branch. This
validation does not locate a checkout or read workflow paths from the flattened
worker mount; workflow verification belongs to the host probe.

Local tests execute only the actual old/new context functions against faithful
module-shaped stubs. They reproduce the original missing-global exception,
prove the corrected hook reaches the exact class used by frozen `run_backtest`, restore
all hooks on success/body/setup failure, reject a different adapter or altered
callsite, and demonstrate the identity/hash guard fails when removed. No local
Core, controller, canonical restoration or financial session runs. Hosted proof
remains necessary before any new financial authority.
