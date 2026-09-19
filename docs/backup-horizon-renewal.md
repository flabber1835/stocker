# GO renewal at an exhausted runtime backup horizon

Decision before implementation on verified main
`8212a55335500b4bbb81853572019d9eb4443724`.

The operator status script feeds the certified GO backup-refresh classifier.
It currently admits up to a million archived segments, while the runtime
allows at most 1,024 objects and 1 GiB of distinct archived payload. A recent,
intact base can therefore produce `backup_ready:true`, skip GO renewal, and
then refuse runtime admission. This is a P1 recovery/availability gap, not
evidence of changed historical strategy returns.

The status chain check must apply the existing runtime object and payload
ceilings before archive hashing. Count the inclusive interval and any required
timeline history, including its actual byte size. Exactly-at-limit chains
remain admissible if all existing integrity checks pass. No limit is raised.
The shell and runtime implementations keep independent arithmetic acceptance
fixtures; tests bind the supported constants to prevent silent contract drift.

For an exhausted horizon only, the chain checker returns status 5 and exactly
`SENTINEL_BACKUP_CHAIN_REASON=RUNTIME_HORIZON_EXCEEDED` on stdout. The status
caller requires both before emitting the single existing machine-reason format
with `BASE_BACKUP_RUNTIME_HORIZON_EXCEEDED` and status 4. Arbitrary failures or
other output cannot become repairable. There is no ready marker on this path.

The existing certified GO refresh may supersede this old horizon with one
new independently verified base. Preserve all earlier media and evidence.
Exhaustion is not proof that the old chain is intact; no old-chain integrity
claim is made when payload verification is skipped. New backup creation and
exact-path status verification must both succeed, under the existing GO
certification, run-token, clean-checkout and inherited backup-lock gates.
A failing or still-over-budget successor refuses; no retry loop or capability
promotion is introduced. Bring-up reuses this same repair classifier.

The independent explicit physical restore drill keeps its own complete-chain
verification, so old retained recovery points are not deleted or made unusable
merely because they exceed the foreground runtime budget. Status remains a
current runtime-preparation checkpoint, not permission to alter old evidence.

Acceptance must drive the actual status shell and production GO refresh with
temporary media: admitted exact-limit and refused over-limit cases, real checksum
validation on admissible chains, fresh successor recovery and failed verification
that cannot become ready. Removal of either early bound, the strict reason
mapping, renewal classification or final verification must fail acceptance.
Use separate low segment-size geometry to exercise the object bound and a
nonempty timeline-history case to exercise total payload accounting.

This is connected GO recovery, not recurring maintenance. Proactive scheduling,
global ownership across supported hosts/UIDs, outage recovery, retention, bounded
directory/manifest inspection and full physical/NAS qualification remain open.
Pending #410's bounded selection is a separate change; this fix starts at
current main and must retain its contract when integrated. No broker access.
