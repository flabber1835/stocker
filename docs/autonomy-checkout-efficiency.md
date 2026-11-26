# Runtime checkout and build context efficiency

Decision: 2026-10-16, before implementation. Runtime and safety workflows need
the complete code, tests, fixtures and source tree identity, but do not consume
the historical `sec-filings` ZIP collection. That collection accounts for
921,904,567 of 1,018,051,333 tracked baseline bytes. Keep it in repository
history and in the dedicated SEC reconstruction workflow. Other ordinary full
checkouts use non-cone sparse patterns `/*` and `!/sec-filings/`; existing
purpose-specific sparse checkouts retain their narrower declared scopes.

The exact tested Git commit/tree and all behavioral source/test hashes remain
unchanged by materialization. Missing runtime or fixture paths are qualification
failures. No independent oracle, research artifact or protected test is deleted.
The Docker context excludes SEC archives, local task worktrees and credentials;
the exact `.env.example` remains available to the image-layout tests. This is a
checkout/context optimization, not a claim that existing Git history shrinks.

## Host checkout enforcement

Decision of 2026-11-26. Use the host checkout command to stage a new exact
revision for routine Sentinel work. It creates a linked worktree without
initial checkout, selects the sparse patterns, then writes the files. The
worktree shares the repository's Git objects and retains the exact commit
and branch selected by the operator.

```sh
python3 scripts/sentinel_local_delivery/checkout.py create \
  --repository "$REPOSITORY" --worktree "$WORKTREE" \
  --branch "$QUALIFICATION_BRANCH" --revision "$COMMIT_SHA"
```

Run `checkout.py check --worktree "$WORKTREE"` before a manual host test or
qualification. The autonomous installation and GO launchers check this
policy before starting operational work. The backed PAPER operational source
manifest also checks it before hashing candidate files, including when it
reads a mounted checkout. Each check refuses a materialized `sec-filings`
path. The full-tree legacy qualification format and the dedicated SEC
reconstruction workflow retain their existing input scopes.

To reclaim existing duplicate copies, select inactive, clean worktrees with
the filing objects available in their shared Git repository. Apply the same
sparse patterns so the checkout retains its branch and can recover the files
from Git. This action is limited to reviewed operational worktrees.

Qualification verifies every changed workflow's checkout options, materializes
the patterns in an isolated Git fixture, and checks runtime/test image builds
and source-identity validation. Report byte savings as omitted materialized
files, separately from measured network transfer or build time.

The supported bringup liveness probe and GO data preflight share the same
host-side marker parser and redacted diagnostic renderer. Keep their public
entry points and distinct markers, but maintain those identical parsing and
redaction rules once. Embedded isolated-runtime probes remain self-contained;
independent certification oracles and orchestrators retain their boundaries.
