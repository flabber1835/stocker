# Installing the CI-certified single runtime

Decision: 2026-10-03. This completes the existing single-runtime contract from
`sentinel-handoff/ci-certified-runtime/PR-C.md` and `PR-D.md` at the reviewed
paper installer. A successful real GO exposed legacy installer checks that
required a distinct candidate image and attempted another image publication.

Normal GO records the same immutable local image ID for its candidate and
runtime roles. Reviewed installation accepts that alias, inspects the image
once, and still requires the exact clean main commit, OCI revision, runtime
source identity, reviewed publication, current account and all admission gates.
The existing explicit local-full path may retain a distinct test lens layered
on the exact runtime; its prefix-layer verification remains mandatory.
Auxiliary image aliases and duplicate inspection records remain refusals.

The reviewed preparation record may include the producer's last 512 sanitized
progress events. The installer validates them with the same bounded progress
parser used by GO. They remain diagnostics; they cannot replace a preparation
PASS, a source proof or any admission gate. Unknown fields and malformed events
remain refusals.

The single-runtime path independently verifies the signed GitHub certification
for current main before entering deployment. It rechecks certification when
selecting the image, binds the registry digest to the reviewed local image ID,
and reuses that immutable registry reference. It never builds, reruns the full
software suite, pushes a replacement image, or treats a local JSON PASS as CI
certification. The legacy test-digest certificate field names the same runtime
digest for this path.

Offline issuer tools are taken from the same verified clean checkout and mounted
read-only at `/app/tools` into this runtime for the issuer invocation only.
Signing retains `--network none`, the existing read-only private-key mount and
the private authority-output mount. The offline tool runs as the host installer
UID/GID so it can read the private key and write private attempt directories
without granting other users access. No second deployable image or persistent
tooling service is introduced. Provider and broker credentials are absent from
the signer. The production runtime modules continue to come from the certified
image, not a source-directory overlay.

This repairs installer conformance; it changes no strategy, account binding,
trust root, signed-certificate requirement, broker endpoint, backup requirement,
fencing or reconciliation rule. A local parser/installer regression test grants
no authority to activate unmerged code. Production activation still waits for
the fixed release's normal merge certification and a matching GO bundle.
