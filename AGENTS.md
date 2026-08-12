# AGENTS.md

# Sentinel

This repository contains one production architecture. Stocker is gone.

```text
Wealth Core   the deterministic alpha engine and its immutable shadow book
Sentinel      a deterministic exposure controller wrapped around it. It decides
              HOW MUCH of the live account is exposed to Wealth Core versus a
              T-bill sleeve. It never decides WHAT Wealth Core holds
```

## Git workflow — PR only

These rules apply to Codex and other coding agents working in this repository.
They are release-safety rules, not style preferences.

1. **The authoritative repository is `flabber1835/stocker`.**
2. **Never develop directly on `main` and never push directly to `main`.** All
   delivered changes must arrive through a pull request targeting `main`.
3. **Before editing, identify both the base-verification method and the delivery
   channel.** Use exactly one of the workflows below. If the workspace has
   neither a working GitHub/PR path nor a way to export a downloadable patch,
   STOP before editing; do not create work that cannot leave the sandbox.

   A connected GitHub app is a valid PR delivery channel. When authenticated
   local `git` can fetch and push and the connected GitHub app has repository
   access, use `git` for base verification, branches, commits, and pushes, then
   use the GitHub app for PR creation and verification. The GitHub CLI (`gh`) is
   optional in this path: its absence, or sandboxed access to its configuration,
   is not by itself a blocker. Request the narrow approval needed for an
   otherwise available authenticated operation instead of telling the user to
   install or re-authenticate tooling that is already configured.

   ### A. Normal local or CLI checkout with shell access to GitHub

   Before changing anything, run and report:

   ```bash
   git remote -v
   git branch --show-current
   git rev-parse HEAD
   git fetch origin main
   git rev-parse origin/main
   ```

   If `origin` is unavailable, `origin/main` cannot be resolved, or the local
   base is not current with `origin/main`, STOP and report the problem. Do not
   implement changes in a disconnected or stale checkout and present them as
   published repository work.

   Create a feature branch from current `origin/main`, preferably
   `codex/<short-task-name>`, push only that feature branch, and open a pull
   request against `main`.

   ### B. Managed coding workspace with a built-in PR handoff

   This path applies only when the platform supplied the repository checkout and
   intentionally blocks shell-level GitHub access while providing its own
   **Create PR** or equivalent publication mechanism.

   - Do not add GitHub tokens, alter credential helpers, weaken proxy settings,
     or repeatedly retry blocked shell network access merely to make `git fetch`
     or `git push` work.
   - Record and report:

     ```bash
     git branch --show-current
     git rev-parse HEAD
     git status --short
     ```

   - Proceed only when the local `HEAD` equals an authoritative `main` SHA that
     was independently supplied by the managed platform, the user, or a
     connected GitHub verification. A SHA observed only inside the same
     disconnected checkout is not independent verification. If no trusted base
     SHA is available, or it does not match, STOP before editing.
   - The managed local branch may remain platform-owned, for example `work`; do
     not require a shell-created remote feature branch when the platform itself
     publishes the PR.
   - Commit changes locally, then use the platform's built-in PR handoff to open
     a pull request against `flabber1835/stocker:main`. Include the verified base
     SHA in the PR description.
   - Shell `git push` is not required in this path. The PR handoff is the
     publication step.
   - Do not report delivery until the platform confirms a GitHub PR number or
     URL. If PR publication fails, immediately fall back to workflow C while the
     local commit is still available.

   ### C. Managed or disconnected workspace without a built-in PR handoff

   This is a **recovery/export path**, not repository delivery. It applies only
   when the checkout's base SHA was independently verified as described above
   and the platform can expose a generated file for download or attachment.

   - Before editing, verify that a generated file can be returned to the user.
     If no artifact/download/attachment channel exists, STOP before editing.
   - Do not add GitHub credentials, change proxies, or weaken sandbox controls.
   - A platform-owned branch such as `work` is acceptable. Record the verified
     base SHA before the first edit and preserve it in the completion report.
   - Commit the complete change locally. Then export the commit range as a
     portable patch, including binary changes if any:

     ```bash
     BASE_SHA=<independently-verified-main-sha>
     HEAD_SHA=$(git rev-parse HEAD)
     git format-patch --binary --stdout "$BASE_SHA..$HEAD_SHA" \
       > /tmp/<task-name>.patch
     git bundle create /tmp/<task-name>.bundle HEAD "^$BASE_SHA"
     sha256sum /tmp/<task-name>.patch /tmp/<task-name>.bundle
     wc -c /tmp/<task-name>.patch /tmp/<task-name>.bundle
     ```

   - Return at least the `.patch` as a downloadable artifact. The `.bundle` is a
     second recovery format when the platform supports binary downloads.
   - Report the verified base SHA, local head SHA, artifact SHA256 and size,
     changed-file list, and exact tests. Keep the working tree clean.
   - Label the result **UNDELIVERED LOCAL WORK** until another GitHub-connected
     agent or developer applies the artifact to current `main`, pushes a feature
     branch, and opens a PR. Do not describe a local commit or exported artifact
     as a pull request or as repository delivery.
   - If the artifact cannot be exposed after implementation, print a complete
     `git format-patch --binary --stdout "$BASE_SHA..$HEAD_SHA"` in numbered,
     lossless chunks as the last-resort recovery and state that reassembly is
     required.

4. **Do not merge your own pull request unless the user explicitly asks you to.**
   The default handoff is: agent codes -> agent tests -> agent opens PR -> user
   reviews/merges.
5. **Never force-push `main`, rewrite published history, or bypass repository
   protections.**
6. If a feature-branch push, PR creation, or artifact export fails, report the
   exact error and stop rather than silently continuing or claiming completion.
7. Before reporting repository delivery, verify that the pull request exists on
   GitHub and targets `main`.

## Most Important Process Rule

Whenever a design decision is made, document it in the design docs before
implementation begins. Architecture choices, communication patterns, data
ownership, safety rules, service boundaries, sequencing, and any explicit
choice between two reasonable options belong in the docs first.

The docs are the source of truth for intent. If code diverges from the docs,
update the docs or the code — not just a comment.

## Most Important Architecture Rule

```text
Sharadar        versioned, atomically published input history
Wealth Core     WHAT to hold. Immutable shadow. Never reads broker state
Sentinel        HOW MUCH of it to hold. Never reads realized exposure
Execution       the only layer that touches a broker
```

The membrane is one-directional. Fills, outages, halts and rejects are inputs to
execution and reconciliation. They are never inputs to Wealth Core or to the
controller.

## Required reading before coding

```text
docs/sentinel-deployment.md            operational ground truth. READ FIRST
docs/sentinel-architecture.md          strategy/controller architecture
docs/sentinel-execution-contract.md    execution and recovery contract
docs/sentinel-controller-certification.md
                                       controller certification state
```

Before touching `sentinel/execution/`, `sentinel/binding.py`,
`sentinel/handover.py`, or feed publication/repair modules, read
`docs/sentinel-execution-contract.md`.

For any task touching Wealth Core, read first, in order:

```text
docs/wealth-core-certification.md
docs/wealth-core-v1.md
docs/wealth-core-defense-plan.md
docs/wealth-core-test-rewrite.md
```

## Standing architecture and safety constraints

- Reuse the canonical Wealth Core implementation; do not create a parallel book.
- Wealth Core remains independent of broker state.
- Sentinel controls exposure only; it does not choose Wealth Core holdings.
- Execution is the only broker-facing layer.
- Sharadar is the production market-data source.
- Preserve the price-domain rules documented in the repository.
- No live credentials in the repo.
- Paper trading only unless the repository's explicit safety contract is changed
  through a separately reviewed design decision.
- UNKNOWN broker outcomes are never silently treated as FAILED.
- Do not add autonomous broker-native liquidation paths that bypass the execution
  contract.
- Preserve long-only, unlevered execution-envelope guards.

## Testing — targeted by default

Use the narrowest test set that covers the changed behavior.

- **Do not run `make test` unless the user explicitly asks for the full suite or
  an irreversible release/certification decision requires it.**
- **Do not run `tests/wealth_core` when Wealth Core was not touched.**
- Run syntax/static checks and directly relevant Sentinel tests for the files and
  contracts changed.
- When adding a guard or invariant, add a falsifier and verify that the test
  actually fails when the guard is removed or broken.
- Do not re-pin golden fixtures merely to make tests green.
- Report exact test commands and results in the PR description or completion
  summary.

## Coding style

```text
Python 3.12
Pydantic for schemas
pytest for tests
Postgres for durable state
Decimal for every quantity and price that reaches a broker
```

Keep modules small and explicit. Prefer typed schemas over clever abstractions.
Avoid unnecessary dependencies.

## Final design principle

```text
Deterministic strategy state
  + versioned input history
  + one execution membrane
  + recoverable command identity
  + convergence after absence
```

Preserve this boundary throughout the codebase.
