# Research evidence content references

P02's outcome suffix exported a 1,627,012,590-byte artifact containing the
1,545,114,261-byte predecessor ZIP as an opaque member. About 95% of the new
transport is therefore duplicate ancestor packaging. The client already keeps
every unique parent member, including original checkpoints, journal prefixes,
recovered tails and older opaque evidence, in its protected private archive.
Its existing capture proof explicitly distinguishes this content archive from
retention of every outer ZIP's exact transport bytes.

Full actual recovery frames also increase the uncompressed current evidence.
The admitted July frame is 761,651 JSON bytes; 753 such frames add about 574 MB.
Keeping both that evidence and a duplicate 1.55 GB ZIP would exceed the current
two-GiB expanded export limit. Neither financial calculation nor proof scope
should be weakened to accommodate transport packaging.

## Storage-only successor

After the stopped parent is fully authenticated and independently admitted,
future exports may replace the newly copied opaque parent ZIP with a strict
content-reference record. Preserve the entire current output unchanged,
including every checkpoint, journal and recovered tail produced by the worker.
Do not edit, delete or recompress any old protected evidence or old artifact.

The reference binds the exact parent run, source head, outer ZIP size/hash,
receipt hash, encrypted-asset and manifest commitments, selected checkpoint,
source binding, independent review, original journals and descriptor set. It
also binds the independently verified private parent-content archive and its
complete member index. It must explicitly say that the new artifact omits
duplicate transport bytes and does not newly claim a second physical copy.
An artifact identifier without the content and financial bindings is
insufficient. Unverified, unknown-stop or failed-review parents cannot use
this normal-successor path.

The private archive remains authoritative for the older evidence. Final
review must verify the complete reference chain and actual retained content,
including opaque older evidence, rather than infer preservation from a link.
The seven-day hosted artifact lifetime is not a claim that the private archive
expires. No cleanup or deletion of that archive is part of this change.

## Admission and qualification

Retain the existing AES-GCM authentication-before-parsing, complete inventory,
exact worker stop/fences, checkpoint/source/input bindings and all journal
prefix checks. For a small reference-based predecessor, use the original
bounded normal artifact admission, with explicit P02/reference scope checked
before network or filesystem mutation. Do not relax the old large-archive
helper or reinterpret its opaque-member assertion.

The normal one-GiB plaintext bound applies to all current unique evidence,
including full recovery frames. An explicit 512-MiB encrypted ZIP bound is
adequate only if measured output fits it; larger output must refuse. The
reference and every current member must be encrypted in the approved channel.
No plaintext financial payload is added to public logs or artifacts.

Qualify source-bound reference construction and mutation refusals with pure
metadata tests, then authenticate an actual hosted reference-based export.
No financial restart, rule/input conversion, new formation, controller change
or production action is authorized by this storage protocol. Continue only
the exact independently admitted own financial suffix.

## Hosted dependency boundary

The first integrated WWE suffix stopped at module import before its main
function: the transfer environment did not include Pydantic. It exported only
the authenticated staging receipt; no financial worker or new origin started.
Preserve that failed run and its exact log. Keep the original transfer lock and
every adopted source byte unchanged. Add a separate hash-locked Pydantic
dependency file for this workflow's metadata schema, using the locally
qualified version and official PyPI wheel digests. Install both locks in the
same transfer environment, then verify the exact request and import closure
before staging inputs. This does not install into or alter the offline image.
A new attempt may use the same admitted predecessor because the prior attempt
never reached its financial launcher; it is not a financial restart.
