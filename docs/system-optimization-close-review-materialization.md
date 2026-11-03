# Hosted closing-input review materialization

Static inspection of the P02 closing-suffix reviewer shows a lifecycle gap:
entering its input codec installs dispatch hooks, but does not itself load an
input. The read-only historical checkpoint reviewer restores state and verifies
journals; it does not populate the codec's loaded-object list. The closing
reviewer's final factual-delta check expects that list to contain its input.
The selected job has now exhibited this exact failure. Both original workers
are proven stopped with exit 1 and no OOM. Complete artifact authentication and
bounded diagnostic retention identify an April 30, 2024 checkpoint with 1,592
measured closes. It remains a review target, not an admitted financial resume.

Prepare a separate review-only adapter rather than editing a running or adopted
driver. Inside the existing six-codec review context, the additional codec must
canonically load the exact seventh descriptor with its original resume cursor
and predecessor binding. It must match the descriptor hash before any review
body proceeds, and restore all dispatch hooks on a load failure. Reuse the
unchanged published review body after materialization. Record the actual loaded
input and exact stopped checkpoint. Do not advance a session or write a book.

After authenticating and retaining the actual stopped output and failure,
admit those immutable bytes only for a
hosted review-only correction with a distinct request and evidence identity.
An earlier checkpoint is not a replacement for those outputs. There is no
financial restart, source/state conversion, altered factual input, or local
canonical execution. PAPER, main, broker/database systems and shared services
remain untouched. This adapter is not authority to launch a second writer.

Use a separate, exact failure-admission scope for the stopped Hostess output.
Keep the original download, ZIP, cipher/GCM, inventory, source, checkpoint and
journal-prefix checks byte identical; replace only the failure classifier with
one bound to this actual run, checkpoint, source and reviewer traceback. Require
explicit review-only and no-financial-resume fields. Restore the complete
artifact on the hosted VM and reuse the separately authenticated October parent
as the review's own predecessor. A successful corrected review does not erase
the original failure or waive the remaining independent evidence requirements.
