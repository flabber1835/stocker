#!/usr/bin/env bash
# deploy.sh — one-command NAS deploy that cannot hit the "dirty strategies/
# tree blocks git pull" trap.
#
# The one-click config Apply (evaluator Phase 3) writes the approved YAML on
# the NAS, so strategies/<active>.yaml legitimately diverges from origin until
# it is mirrored back into git. This script codifies the documented routine
# (CLAUDE.md "Deployment (Synology NAS)"):
#
#   1. Refuse to run off main, or with uncommitted changes to TRACKED files
#      outside strategies/ (those would break the rebase — resolve by hand).
#   2. If strategies/ is dirty: each dirty file must byte-match an artifact in
#      artifacts/config/applied/ (the canonical copy written by the Apply
#      endpoint). Matching files are auto-committed ("mirror applied config");
#      a non-matching file aborts — that is a stray manual edit, not an
#      approved apply, and a human must resolve it.
#   3. git fetch + rebase origin/main, then push (with retry/backoff).
#   4. docker compose up -d --build <services...> for the services passed as
#      arguments. No arguments = no build (prints a hint), so the git steps
#      can be run standalone.
#
# Usage: scripts/deploy.sh [service ...]
#   e.g. scripts/deploy.sh api pipeline portfolio-builder
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

APPLIED_DIR="artifacts/config/applied"

# Never prompt for credentials — an interactive username/password prompt hangs
# the deploy (and swallows pasted commands). A push without credentials should
# FAIL FAST and be reported, not block.
export GIT_TERMINAL_PROMPT=0

info() { echo "deploy: $*"; }
err()  { echo "deploy: ERROR: $*" >&2; exit 1; }

retry() { # retry <cmd...> — retries with backoff (network flake); DEPLOY_BACKOFF overridable for tests
    local delays=(${DEPLOY_BACKOFF:-2 4 8 16}) n=0
    until "$@"; do
        [ "$n" -ge "${#delays[@]}" ] && return 1
        info "'$*' failed — retrying in ${delays[$n]}s..."
        sleep "${delays[$n]}"
        n=$((n + 1))
    done
}

branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$branch" = "main" ] || err "on branch '$branch' — deploys run from main only"

# ── 1. classify working-tree state ────────────────────────────────────────────
# Porcelain lines are "XY <path>" (XY = 2 status chars, then a space).
dirty_all="$(git status --porcelain)"
dirty_strat="$(printf '%s\n' "$dirty_all" | grep -E '^.{2} strategies/' || true)"
dirty_other="$(printf '%s\n' "$dirty_all" | grep -vE '^.{2} strategies/' | grep -v '^$' || true)"

# Untracked junk outside strategies/ can't break a rebase — warn only.
# Modified/staged/deleted TRACKED files would break it — abort.
blocking_other="$(printf '%s\n' "$dirty_other" | grep -v '^??' | grep -v '^$' || true)"
if [ -n "$blocking_other" ]; then
    printf '%s\n' "$blocking_other" >&2
    err "uncommitted changes to tracked files outside strategies/ — resolve by hand first"
fi
if [ -n "$dirty_other" ]; then
    info "note: untracked files outside strategies/ present (ignored):"
    printf '%s\n' "$dirty_other"
fi

# ── 2. mirror applied config changes into git ────────────────────────────────
if [ -n "$dirty_strat" ]; then
    mirrored=""
    while IFS= read -r line; do
        f="${line:3}"
        [ -f "$f" ] || err "strategies file '$f' was deleted locally — the Apply flow never deletes; resolve by hand"
        match=""
        # newest artifact first — the applied/ copy is byte-canonical
        for art in $(ls -t "$APPLIED_DIR"/*.yaml 2>/dev/null || true); do
            if cmp -s "$f" "$art"; then match="$art"; break; fi
        done
        if [ -z "$match" ]; then
            err "'$f' is dirty but byte-matches NO artifact in $APPLIED_DIR/ — \
this is a stray manual edit, not a one-click Apply; resolve by hand \
(compare with the config_changes audit rows before discarding anything)"
        fi
        cfg_hash="$(sha256sum "$f" | cut -c1-16)"
        info "mirroring '$f' (config $cfg_hash, matches $(basename "$match"))"
        git add "$f"
        mirrored="$mirrored$f (config $cfg_hash); "
    done <<< "$dirty_strat"
    git commit -m "mirror applied config change: ${mirrored% }"
    info "mirror commit created"
fi

# ── 3. rebase on origin/main and push ────────────────────────────────────────
compose_before="$(git rev-parse HEAD:docker-compose.yml 2>/dev/null || echo none)"
retry git fetch origin main || err "git fetch failed after retries"
git rebase origin/main || err "rebase failed — resolve conflicts by hand (git rebase --abort to back out)"

# Push only when there is something local to push; a failed push (e.g. a
# pull-only NAS clone without a write key) warns LOUDLY but never blocks the
# deploy — local commits rebase cleanly on future pulls until credentials exist.
ahead="$(git rev-list --count origin/main..HEAD)"
if [ "$ahead" -gt 0 ]; then
    if retry git push -u origin main; then
        info "pushed $ahead local commit(s) to origin/main"
    else
        info "WARNING: git push failed ($ahead local commit(s) remain unpushed —"
        info "         likely no write credentials on this clone). Deploy continues;"
        info "         the commit(s) rebase cleanly on future pulls. Add a write"
        info "         deploy key to make the mirror land on GitHub automatically."
    fi
else
    info "nothing to push (local main == origin/main)"
fi
compose_after="$(git rev-parse HEAD:docker-compose.yml 2>/dev/null || echo none)"

info "HEAD is now: $(git log --oneline -1)"
if [ "$compose_before" != "$compose_after" ]; then
    info "NOTE: docker-compose.yml changed in this pull — run"
    info "      'docker compose down --remove-orphans' once (NEVER with --volumes)"
    info "      to evict ghost containers before/after the build."
fi

# ── 4. rebuild the changed services ──────────────────────────────────────────
if [ "$#" -gt 0 ]; then
    info "building + restarting: $*"
    docker compose up -d --build "$@"
else
    info "no services passed — skipping docker build."
    info "usage: scripts/deploy.sh <changed-services...>  (e.g. api pipeline)"
    info "reminder: a change under shared/ requires rebuilding EVERY service that"
    info "imports it, and a brand-NEW shared module additionally requires 'make build-base' first."
fi
