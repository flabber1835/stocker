# PR 402 local pre-NAS evidence

**Economic certification remains blocked.** Read the
[review, ledger and NAS handoff](../../../docs/economic-audit-399-pre-nas.md).
`local-evidence.zip` is this campaign's evidence, not a provider certificate.
`evidence.json` records its byte count, SHA256, reviewed source and verified base.
The archive contains a SHA256/size manifest, full stdout and JUnit results,
exact command argument arrays, runner sources, both synthetic golden captures,
and six lifecycle traces with deterministic provider transcripts. Failed first
attempts are retained and identified in the report. No credentials are included;
the physical runner contains only an explicitly test-only publication key.

The archive's `retained-source/` files are verified against immutable audit
commit `ec9623070908b437222b2e1d963d3ceb8721f9bb` after CRLF normalization.
`source-provenance.json` preserves original and executed-byte SHA256 separately.
Keep the original golden/reference files unchanged.

## Reproduce isolated local campaigns

Use a disposable checkout of the reviewed code and a **new** writable evidence
directory, never the retained evidence directory. Extract `campaign/*.py` and
`campaign/changed-python.json` into that new directory. Copy `retained-source/`
into the disposable checkout's `.codex-tmp/audit399-source/`, retaining its tree.
Create an empty file for the `.env` overlay. The existing test image must contain
Python 3.12, repository test dependencies and PostgreSQL binaries. The exact
local image/runtime used is recorded in the report. Do not attach account
credentials or permit container networking.

The executed Docker envelope below uses the original Windows host paths;
replace them with the disposable checkout and new evidence paths. The recorded
runner was mounted at `/repo/.codex-tmp/audit402-prenas/`; `/evidence/` is the
same directory through the separate writable mount.

```powershell
docker run --rm --network none `
  --mount type=bind,source=C:/GitHub/stocker,target=/repo,readonly `
  --mount type=bind,source=C:/GitHub/stocker/.codex-tmp/audit402-prenas/empty.env,target=/repo/.env,readonly `
  --mount type=bind,source=C:/GitHub/stocker/.codex-tmp/audit402-prenas,target=/evidence `
  --workdir /repo `
  -e PYTHONPATH=/repo:/repo/shared -e PYTHONDONTWRITEBYTECODE=1 `
  -e SENTINEL_REPO_ROOT=/repo -e ALPACA_HARNESS_REQUIRE_POSTGRES=1 `
  --entrypoint python sentinel-test:ci `
  /repo/.codex-tmp/audit402-prenas/run_campaign.py acceptance
```

Replace `acceptance` with `restore-push`, `regression`, `strategy`, `cash-crash`,
`predecessor`, `sse-wire` or `golden-unmasked`. `run_campaign.py` retains the
literal pytest file/node selections and sets STRICT_V1 where required. Replace
the final script/argument with `replay_golden.py` for golden captures; immutable
historical commit `5afba080859f25ea65fdb82da9ba54b442bac368` must be available
locally. `golden-unmasked` intentionally exits nonzero on the three old oracles.

The exact original `clean_replay.py physical` and `clean_replay.py lifecycle`
runner clones the named branch and asserts commit `354a431a`. To reproduce it,
point that branch in a **disposable checkout only** at that immutable commit.
Do not reset the published feature branch. The physical runner copies the two
retained tests into the clean temporary clone, uses a test-only receipt key,
and makes the parent traversable by the local postgres user. Those adjustments
provide test infrastructure and do not bypass production restore checks.

Mutation commands, with the same isolated Docker envelope:

```sh
python tools/v5_mutation_check.py
python tools/champion_mutation_check.py
python tools/economic_audit_mutation_check.py fills
python tools/economic_audit_mutation_check.py coverage
python tools/economic_audit_mutation_check.py attempt
python tools/economic_audit_mutation_check.py durable-fills
python tools/economic_audit_mutation_check.py terminal-split
python tools/economic_audit_mutation_check.py restore-origin
python tools/economic_audit_mutation_check.py push-attempt
python tools/economic_audit_mutation_check.py snapshot-replay
python tools/validate_test_responsibility.py --base aff4461d9af6d4a7367018768fda18d948958b49
```

`check_source.py` compiles the changed-file inventory and compares pyflakes
diagnostics to `97a5fb45`; it expects the existing local pyflakes dependency
under `.codex-tmp/lint-deps`. Provision that dependency in the disposable local
environment before running it; the test container remains offline.

The archive's `*.command.json` files are the exact executed argument arrays
and exit codes. The two corrected mutation reruns have full `*-fixed.log`
output rather than a command JSON; their commands are listed above. Initial
red-test commands are identified by JUnit test node identities. Do not treat
the intentional mutation failures, old golden failures or superseded harness
errors as unexplained production test regressions.
