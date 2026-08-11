#!/usr/bin/env python3
"""Build Sentinel's `.env` from the retired Stocker one, by SUBTRACTION.

## Why this is a script and not a copy

The old file has ~40 variables and Sentinel reads six of them. Copying it
wholesale is not merely untidy — it carries three specific hazards:

```text
PAPER_ONLY=true             read by NOTHING. The only surviving mention is a
LIVE_TRADING_ENABLED=false  COMMENT in sentinel/config.py describing the design
KILL_SWITCH=false           that was deleted. A line that looks like a safety
MAX_ORDER_NOTIONAL          interlock and is inert is worse than no line: the
                            real guard is LIVE_HOSTS in sentinel/config.py, and
                            somebody reading the .env would not know that
ALPACA_BASE_URL             if the old deployment ever pointed at the live host,
                            copying it forward hands Sentinel a value it will
                            refuse to start on — a confusing failure, and a
                            fact about the old book worth surfacing loudly
AV_API_KEY, ANTHROPIC_...   credentials for services that no longer exist. A
TAVILY_API_KEY, IBKR_*      secret with no consumer is pure liability
```

So the whitelist below is the contract, and everything absent from it is
dropped by construction rather than by anyone remembering to.

## It never prints a value

Not to stdout, not to a log, not in an error. The report names variables and
says what happened to them. That is deliberate: this runs on a NAS over SSH,
and a terminal that has echoed a Sharadar key has put it in scrollback, in the
shell history of anyone who scrolled, and in any transcript of the session.

## Usage

    scripts/sentinel-env-from-stocker.py --from ~/stocker-old/.env
    scripts/sentinel-env-from-stocker.py --from ../legacy/.env --to .env --force

Writes mode 0600. Refuses to overwrite without `--force`.
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
import stat
import sys
from pathlib import Path

#: Read by Sentinel, and carried across if present. The comment on each is why
#: it survives — verified against the source, not against the old .env.example,
#: which still describes the deleted runtime.
CARRY: dict[str, str] = {
    "SHARADAR_API_KEY":
        "the corpus. sentinel/feed/sharadar.py. THE SEED CANNOT RUN WITHOUT IT",
    "ALPACA_API_KEY":
        "sentinel/config.py. Not needed for #15; needed for the paper leg",
    "ALPACA_SECRET_KEY":
        "sentinel/config.py",
    "BT_POSTGRES_PASSWORD":
        "only step 8b of sentinel-certify.sh, the canonical-corpus comparison",
    "NDL_BASE_URL":
        "optional. Nasdaq Data Link endpoint override",
    "SHARADAR_FETCH_TIMEOUT": "optional tuning",
    "SHARADAR_FETCH_RETRIES": "optional tuning",
    "SHARADAR_FETCH_BACKOFF": "optional tuning",
    "SHARADAR_429_BACKOFF_CAP": "optional tuning",
}

#: Required for the seed. Absent or placeholder is a REFUSAL, not a warning:
#: discovering it when `feed-seed` dies is a wasted trip to the NAS.
REQUIRED = ("SHARADAR_API_KEY",)

#: Generated here because the old file has no equivalent, and compose declares
#: it `${SENTINEL_POSTGRES_PASSWORD:?...}` — it REFUSES to start without one
#: rather than falling back to a word everybody knows.
GENERATE = {
    "SENTINEL_POSTGRES_PASSWORD":
        "not in the Stocker file; compose refuses to start without it",
}

#: Dropped, and NAMED in the report rather than dropped silently. Anyone who
#: believed these were in force needs to be told they are not.
INERT_SAFETY = {
    "PAPER_ONLY", "LIVE_TRADING_ENABLED", "KILL_SWITCH",
    "MAX_ORDER_NOTIONAL", "MAX_ORDER_PCT",
}

#: Never carried forward even when present. Sentinel writes its own.
FORCED = {
    "ALPACA_BASE_URL": "https://paper-api.alpaca.markets",
}

#: The host that reaches real money. Mirrors sentinel/config.py LIVE_HOSTS —
#: duplicated rather than imported because this script must run before the
#: package is importable, on a host that may only have the checkout.
LIVE_HOSTS = frozenset({"api.alpaca.markets"})

#: Values that are documentation, not credentials. The old .env.example ships
#: with these, and a file that was copied from it and never filled in would
#: otherwise pass every check here and fail hours later.
_PLACEHOLDER = re.compile(
    r"^(your_.*_here|changeme|xxx+|todo|<.*>|\.\.\.)$", re.I)


def parse_env(path: Path) -> dict[str, str]:
    """Compose's `.env` semantics, narrowly.

    Quoted values are taken verbatim. Unquoted ones have a whitespace-preceded
    `# comment` stripped, which is what compose does and what the old file
    relies on (`STRATEGY_CONFIG_PATH=... # NOT CONSUMED`). Stripping it
    unconditionally would corrupt any value legitimately containing ` #`.
    """
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", key):
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        else:
            val = re.split(r"\s+#", val, maxsplit=1)[0].rstrip()
        out[key] = val
    return out


def is_usable(val: str) -> bool:
    return bool(val) and not _PLACEHOLDER.match(val)


#: Passwords compose splices into a DSN:
#:   postgresql://sentinel:${SENTINEL_POSTGRES_PASSWORD}@sentinel-postgres:5432/…
#: Any of these characters ends the password early or moves the host, and the
#: resulting error names a connection, not a password.
_DSN_HOSTILE = set(":/@?#[]%")

#: Compose interpolates `${...}` inside the `.env` it reads for the compose
#: file, so a literal `$` in a value is not the value. Escaping it silently
#: would be worse than saying so — the operator has to decide.
_INTERPOLATES = "$"


def quote(val: str) -> str:
    """Emit a value that survives both compose and `source`.

    Unquoted was the first version, and `BT_POSTGRES_PASSWORD=btpass with
    spaces` came out of it: legal to compose, fatal to `source`, and truncated
    by anything that strips a whitespace-preceded comment.
    """
    if val and not re.search(r"[\s#\"'\\$]", val):
        return val
    # SINGLE quotes when the value allows them: compose treats a single-quoted
    # value as literal and performs no `${...}` interpolation inside it, and so
    # does `source`. Double quotes would leave a `$` live in both. The warning
    # about `$` still fires, because compose versions have differed on this and
    # a value the operator cannot see is worth one line of noise.
    if "'" not in val:
        return "'" + val + "'"
    return '"' + val.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(carried: dict[str, str], generated: dict[str, str]) -> str:
    """The output file. Comments explain provenance; values appear once."""
    lines = [
        "# Sentinel — generated by scripts/sentinel-env-from-stocker.py",
        "# Derived from the retired Stocker .env by SUBTRACTION: only the",
        "# variables Sentinel's source actually reads were carried across.",
        "#",
        "# NOT carried, deliberately: PAPER_ONLY, LIVE_TRADING_ENABLED,",
        "# KILL_SWITCH and MAX_ORDER_* are read by NOTHING in this repository.",
        "# The guard that stops Sentinel reaching real money is LIVE_HOSTS in",
        "# sentinel/config.py, which refuses api.alpaca.markets and has no",
        "# override. Re-adding the old flags would not add protection.",
        "#",
        "# Never commit this file. .gitignore line 22 covers it.",
        "",
    ]
    if generated:
        lines.append("# ── generated here ─────────────────────────────────")
        for k in sorted(generated):
            lines.append(f"# {GENERATE[k]}")
            lines.append(f"{k}={quote(generated[k])}")
        lines.append("")
    lines.append("# ── carried from the Stocker file ──────────────────────")
    for k in sorted(carried):
        lines.append(f"# {CARRY[k]}")
        lines.append(f"{k}={quote(carried[k])}")
    lines.append("")
    lines.append("# ── forced, not inherited ──────────────────────────────")
    lines.append("# Sentinel refuses to start against the live host; this is")
    lines.append("# belt-and-braces on a guard that is already unconditional.")
    for k, v in sorted(FORCED.items()):
        lines.append(f"{k}={v}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="src", required=True,
                    help="the retired Stocker .env")
    ap.add_argument("--to", dest="dst", default=".env")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing destination")
    ap.add_argument("--dry-run", action="store_true",
                    help="report only; write nothing")
    a = ap.parse_args(argv)

    src, dst = Path(a.src).expanduser(), Path(a.dst).expanduser()
    if not src.is_file():
        print(f"REFUSED: {src} is not a file", file=sys.stderr)
        return 2
    if dst.exists() and not (a.force or a.dry_run):
        print(f"REFUSED: {dst} already exists. Re-run with --force to replace "
              f"it, after checking it is not the one in use.", file=sys.stderr)
        return 2

    old = parse_env(src)

    carried, skipped_empty, dropped_inert, dropped_retired = {}, [], [], []
    for k, v in old.items():
        if k in FORCED:
            continue
        if k in CARRY:
            (carried.__setitem__(k, v) if is_usable(v)
             else skipped_empty.append(k))
        elif k in INERT_SAFETY:
            dropped_inert.append(k)
        else:
            dropped_retired.append(k)

    generated = {k: secrets.token_urlsafe(24) for k in GENERATE
                 if k not in old or not is_usable(old.get(k, ""))}
    for k in GENERATE:
        if k in old and is_usable(old[k]):
            carried[k] = old[k]
            CARRY.setdefault(k, GENERATE[k])

    # ── the report. NAMES only, never values ─────────────────────────────────
    def say(title, names, note=""):
        if not names:
            return
        print(f"\n  {title}")
        for n in sorted(names):
            print(f"    {n}")
        if note:
            print(f"    -> {note}")

    print(f"reading {src}  ({len(old)} variables)")
    say("CARRIED", carried)
    say("GENERATED", generated, "a fresh secret; nothing in the old file "
                                "supplied one")
    say("PRESENT BUT EMPTY OR A PLACEHOLDER", skipped_empty)
    say("DROPPED — read by NOTHING in this repository", dropped_inert,
        "if you believed these were in force, they were not. The guard is "
        "LIVE_HOSTS in sentinel/config.py")
    say(f"DROPPED — retired with Stocker ({len(dropped_retired)})",
        dropped_retired)

    # ── refusals ─────────────────────────────────────────────────────────────
    missing = [k for k in REQUIRED if k not in carried]
    if missing:
        print(f"\nREFUSED: {', '.join(missing)} is absent, empty or a "
              f"placeholder in {src}. The seed cannot run without it, and "
              f"finding that out when feed-seed dies is a wasted trip.",
              file=sys.stderr)
        return 1

    # ── two ways a CARRIED value is wrong without being empty ────────────────
    # Both are reported by NAME and both are advisory: the operator owns the
    # old credential and only they can rotate it. Refusing would strand them.
    dsn_risk = [k for k in ("BT_POSTGRES_PASSWORD",)
                if k in carried and (set(carried[k]) & _DSN_HOSTILE
                                     or re.search(r"\s", carried[k]))]
    if dsn_risk:
        print(f"\n  WARNING: {', '.join(dsn_risk)} contains a character that "
              f"compose splices\n  into a database URL — one of :/@?#[]% or "
              f"whitespace. It will not fail as a\n  bad password; it will "
              f"fail as a bad host or a refused connection. Change it\n  in "
              f"both places, or expect step 8b to mislead you.")

    interp = [k for k in carried if _INTERPOLATES in carried[k]]
    if interp:
        print(f"\n  WARNING: {', '.join(sorted(interp))} contains a literal "
              f"'$'. Compose interpolates\n  ${{...}} inside this file, so the "
              f"value it delivers is NOT the value you see.\n  Double the "
              f"dollar sign ($$) or rotate to a credential without one.")

    live = old.get("ALPACA_BASE_URL", "")
    if any(h in live for h in LIVE_HOSTS):
        print("\n  NOTE: the Stocker file's ALPACA_BASE_URL pointed at the "
              "LIVE host.\n  It was NOT carried across — the output pins the "
              "paper endpoint — but it\n  means the retired deployment was "
              "configured against real money. Worth\n  knowing before the "
              "paper leg, and worth rotating those keys.")

    if a.dry_run:
        print(f"\n--dry-run: {dst} not written")
        return 0

    dst.write_text(render(carried, generated))
    os.chmod(dst, stat.S_IRUSR | stat.S_IWUSR)          # 0600
    print(f"\nwrote {dst}  (mode 0600, {len(carried) + len(generated)} "
          f"variables)")
    print("  it is gitignored; do not commit it, and do not echo it over SSH")
    return 0


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
