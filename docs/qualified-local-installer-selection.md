# Qualified application package as local installer

Decision 2026-11-10 before changing the installer selector. The existing immutable
9bac2abb4d0b7dd557197720664b255da1fd68ae adapter rejects the next operational
qualification inventory because its reader omits the now-mandatory tracked
maintenance handover tool and direct test when those files are unchanged.
The rejection occurs during build admission, before application mutation.

Use the clean, qualified application package as the executing installer package.
Its qualification inventory includes the complete sentinel_local_delivery package,
sentinel_backed_local_patch.py, the handover tool/test and every changed tracked
input. Its combined private qualification executes the direct CLI and handover
tests. Independently compare the complete installer package and public backed
entrypoint against qualified9bac: only qualification.py may differ, and its bytes
must equal the already-tested candidate. Retain that comparison and both reports.

Select it atomically under the existing host ownership lock only after validating
the clean package, qualification digest, current VERIFIED application receipt and
healthy preserved application identities. Keep old installed packages immutable.
Continue through the same public build/prepare/resume CLI and all existing
financial, source, environment and pre-open guards. This changes the qualified
reader of the inventory, not the report, its source scope or an admission verdict.
Retain the refused build and its exact diagnostics. Never drop mandatory files,
manufacture a changed file, weaken the qualification comparison or edit installed
source to get past the refusal. The new documentation is the only addition after
the1215-test run; independently bind it while preserving all tested executable and
test bytes and all original logs.
