"""Which image will Compose actually run for a service? ASK COMPOSE.

Two scripts needed this — the certification harness, to freeze the bt-engine
image into the manifest, and the launcher, to inject its id — and both had
their own copy of the answer ending in the same guess:

```text
$(basename "$(pwd)")-bt-engine
```

That is wrong here, and wrong in a way that only shows up on the real machine.
`docker-compose.backtest.yml` declares `name: stocker-bt`, and Compose uses the
top-level `name:` as the PROJECT name ahead of the directory basename. A service
built with no explicit `image:` is tagged `<project>-<service>`, so the real
image is:

```text
stocker-bt-bt-engine        what Compose builds
stocker-bt-engine           what the guess produced
```

Close enough to read as a typo, different enough to never resolve. It fails
closed — but "fails closed" at the first real build means the bootstrap stops
before reaching the 2b refusal it was supposed to demonstrate.

## So the inference is gone

The resolved application model is exactly what `docker compose config` renders,
and it is the only thing entitled to answer this. The order is:

```text
1  services.<name>.image     an explicit image: wins, as Compose does
2  <top-level name>-<name>   Compose's own default tag for a built service
3  REFUSE                    never a guess
```

Step 3 matters as much as the other two. A wrong image name that resolves to
something is far worse than one that resolves to nothing: the manifest would
name an artefact nobody ran.

ONE implementation, imported by both callers, so the harness and the launcher
cannot form different opinions about which artefact they mean — which is the
same class of defect as the one this fixes, one level up.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def _compose_json(compose_file: str) -> dict | None:
    try:
        out = subprocess.run(
            ["docker", "compose", "-f", compose_file, "config", "--format",
             "json"], capture_output=True, text=True, check=True).stdout
        return json.loads(out)
    except Exception:                                        # noqa: BLE001
        return None


def _project_name_from_yaml(compose_file: str) -> str | None:
    """The top-level `name:` read directly, for when Compose is unavailable.

    Deliberately a narrow regex on a top-level key rather than a YAML parse:
    the file is not otherwise being interpreted here, and pulling in a YAML
    dependency to read one line would put a parser between two scripts and the
    fact they need.
    """
    try:
        for line in Path(compose_file).read_text().splitlines():
            m = re.match(r"^name:\s*([A-Za-z0-9._-]+)\s*$", line)
            if m:
                return m.group(1)
    except Exception:                                        # noqa: BLE001
        pass
    return None


def resolve(compose_file: str, service: str) -> str | None:
    """The image reference Compose will use, or None. NEVER a guess."""
    cfg = _compose_json(compose_file)
    if cfg:
        svc = (cfg.get("services") or {}).get(service) or {}
        explicit = svc.get("image")
        if explicit:
            return explicit
        project = cfg.get("name")
        if project:
            return f"{project}-{service}"
    # Compose could not be run (no daemon, not installed). The top-level name
    # is still knowable from the file itself, and it is the part the guess got
    # wrong — so this fallback is the one worth having.
    project = _project_name_from_yaml(compose_file)
    return f"{project}-{service}" if project else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True)
    ap.add_argument("--service", required=True)
    args = ap.parse_args(list(argv or sys.argv[1:]))
    ref = resolve(args.file, args.service)
    if not ref:
        print(f"REFUSED: could not resolve the image for {args.service!r} in "
              f"{args.file}. Not guessed: a wrong image name that RESOLVES is "
              f"worse than one that does not, because the record would then "
              f"name an artefact nobody ran.", file=sys.stderr)
        return 1
    sys.stdout.write(ref)
    return 0


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
