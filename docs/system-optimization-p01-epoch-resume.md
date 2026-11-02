# P01 admitted source epoch continuation

The admitted OWN526 checkpoint at February 4, 2020 belongs to the CELG source
epoch: 516 physical files, 224 canonical financial source files and ten archived
input documents. Its original 515-file source-binding document is historical
evidence. The separately bound successor source map describes the current tree.
The next source session is February 5. Neither the OWN475 book nor the source
boundary may be replayed or emitted again.

`p01_epoch_parent.admit(destination, key, spec)` authenticates the exact retained
439-source bridge artifact through the existing AES-GCM transport. It validates
both complete inventories before interpreting their private contents, the actual
three successful offline worker stops, the public capacity and marker proofs,
the admitted checkpoint, source-map/receipt lineage, ten document bytes and every
committed journal prefix with zero current tails. It does not restore a strategy
state or repeat historical accounting. The caller supplies a public metadata
projection of root admission descriptor
`2799bc888566c90627728341ca3d6ba455143f00e60a0dd3b5131c6d9b801886`;
no local paths or captured quote values are required in that projection.

`p01_epoch_resume.historical_epoch(old, out, spec, ...)` is a hosted context. It
first validates the admitted raw checkpoint and source lineage without restoring
it. It authenticates the already approved quote capsule mounted read-only at
`/celg-input`, checks the complete descriptor, and registers its exact historical
quote. It then enters the unchanged eight ordinary/distribution input contexts,
the ninth DTV codec and the tenth CELG codec, and loads every archived document in
descriptor order. Only after all ten codecs and the quote are ready does it yield
to a caller that may perform canonical Ledger/SessionState restoration.

The yielded binding exposes `parent`, `source_map`, `quote`, `descriptor`,
`objects`, `source_gate`, `source_receipt_path` and `source_args`. Caller code owns
all disposable book/checkpoint/journal/tail copies. The context creates only its
hydration evidence under `out/contexts`; it never creates or changes a financial
checkpoint, quantity, cash balance or journal prefix.

The new `EpochSourceGate` is a continuation gate for this already committed
source epoch. It verifies the exact archived receipt, current source map and
current checkpoint, and returns the admitted source base with no source binding
event. Legacy source schemas delegate to the unchanged canonical loader. It
does not relabel the old OWN475 gate or authorize arbitrary later checkpoints.
The archived `--source-successor` argument is retained because canonical backtest
constructs its base inline without `source_successor_sha256`. The gate restores
that existing metadata and returns binding `None`; canonical backtest therefore
neither archives a new source receipt nor appends a new source boundary. No
canonical base-construction AST or financial algorithm is changed.
The admitted OWN526 checkpoint is initially the only registered checkpoint.
`allow_input(checkpoint, overlay_sha256, earliest)` can register an eleventh input
zero only after the existing canonical adoption checker proves unchanged full
state, source, reports, old input order and the exact new input boundary. Future
financial startup is still required to prove actual zero-session resume, unchanged
watch-stream source-event count and prefix bytes, exact input boundary and
canonical restore before traversal. A constant counter is not that proof.

These helpers admit no new financial result themselves. They retain the explicit
four-path platform-qualified derived CAGR limitation in the root admission;
unexported hosted argument bits remain unknown. New grouped factual inputs,
runtime roles, qualifier/traversal, workflow and publication belong to the caller.
Tests use source metadata, typed objects, crypto and runtime stubs only. No local
canonical strategy/controller execution is permitted.
