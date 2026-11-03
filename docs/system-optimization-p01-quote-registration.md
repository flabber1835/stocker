# P01 immutable quote registration across research contexts

The authenticated 497-source qualification stopped in the historical quote
loader. The admitted 516-source `merger_rights.bind_market_quote` permits exactly
one registration per process and retains its immutable quote after a context
exits. The frozen epoch loader authenticates the capsule and unconditionally
calls that binder on every context entry. Reference and FAST qualification
branches enter separate historical contexts in the same process. This is an
outside-driver lifecycle mismatch; neither a new quote nor a canonical source
change is needed.

The canonical once-only binder and all 516 source bytes remain unchanged. Every
new context must still authenticate the complete approved capsule, descriptor,
member inventory and source/hash domains. Only after authentication may the
driver inspect the canonical `quote()` value. An exact frozen UNBOUND error
authorizes the original single bind. An existing registration must match the
entire freshly authenticated quote by typed canonical encoding and SHA. A
different identity, value, type or source refuses. Any unrelated exception
propagates. No registry reset, replacement, private-global assignment or second
bind is introduced.

`p01_iac_quote_epoch.py` will expose the unchanged historical-context API. It
source-binds the actual `_quote` loader and substitutes its sole unconditional
bind call with the lifecycle helper, retaining all existing authentication and
return checks. It then injects that exact loader into the frozen own628 epoch
function's namespace. This covers the actual imported alias passed into the
eleven-codec hydrator, rather than changing an unused module attribute. The new
runtime must explicitly select this context; published 497 files are immutable.

This registry contains versioned market input, not financial state. Each branch
still has its own source gate, old-input codecs, zero boundaries and book copy.
No qualifier state becomes a financial predecessor. A future qualifier may reuse
the separately reviewed actual reference/component records only after root
approves a concrete proof-bound integration; its next request and scope remain
unselected until that review. Fresh finance, when authorized, still starts from
original admitted own628.

Local tests use the actual old loader function with module-shaped metadata stubs
to reproduce its second-context refusal. They exercise repeated exact admission,
every-entry authentication, mismatched existing quote identity/value/type/source,
descriptor or capsule refusal, and unrelated-error propagation. They verify the
actual frozen namespace and alias callsite without importing or executing Core,
canonical serializers, a controller or financial transitions. Root alone
publishes/selects a complete successor after review.
