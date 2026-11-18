# WAL proof contention during source publication

The November 17 PAPER activation log records two backup waits while publishing
the same closed session. The first followed a 58-second candidate validation.
The second occurred 68 milliseconds into final publication, after an 87-second
source corroboration. Reclaiming the preparation job repeated validation and
corroboration. The backup reader had reported that the previous completed
receipt no longer covered the WAL it observed while another proof owner was
active. Publication eventually succeeded. The log does not identify which WAL
object changed.

Keep a claimed operational preparation job at its preflight or final writer
admission while an exclusive integrity scrub is busy. Retry only the typed
backup ownership failure raised before publication starts. Each attempt runs
the current full backup guard. Release both corpus lock levels and the failed
transaction before waiting. Recheck the same job owner, fence, original
deadline, lease and enclosing acquisition deadline before retrying. Bound the
whole wait at each boundary by the existing corpus writer drain budget.
Publication still checks the durable candidate, validation, CAS, identity and
ownership in its normal writer scope. The final writer has two distinct
durability gates. The corpus lock checks its own guard at entry, and the
snapshot publisher checks backup authority after read-only CAS and identity
checks, before appending any history or receipt. Either gate can yield the
writer and retry the admission. Only the exact latter proof may explicitly
identify its failure as preceding mutation. Failures after these gates and
lost connections use the existing recovery behavior. A waiting job cannot
reissue a commit.

This changes only the scheduling of a failed proof before mutation. Qualify
that the fixed pipeline retains its mandatory preflight call and can reach
corroboration only after it succeeds. Its historical source commitment and
economic identity remain verifiable.
