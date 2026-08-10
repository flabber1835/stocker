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

## The fallback used to break that same order

When `docker compose` cannot be run, resolution still has to reach an answer or
refuse. The first version of that path read the top-level `name:` with a regex
and derived `<project>-<service>` — skipping step 1 entirely. Given

```yaml
name: someproject
services:
  svc:
    image: ghcr.io/example/thing:1.2.3
```

it returned `someproject-svc`: a DERIVED name for a service that had declared
its image outright. The resolver contradicted its own contract, and it did so by
exactly the mechanism it was written to remove — reading the one key it had been
burned by and treating silence about the others as absence.

It survived its own test because `test_an_explicit_image_wins` ran wherever
`docker compose config` was available, so the assertion about the contract only
ever exercised the authoritative branch. A degraded path needs its degradation
exercised, not just its existence.

The file is now PARSED, exactly, by PyYAML — not scanned. That is not a homemade
parser and it can see both keys, so step 1 comes first here too. What the parser
CANNOT see, it refuses over: it reads the file as written, while Compose reads a
resolved application model, and those differ in ways that would produce a
confident wrong answer.

```text
no PyYAML / unparseable      cannot attribute image: to a service      REFUSE
service not in the file      absent is not "has no explicit image"     REFUSE
image: contains ${...}       uninterpolated; Compose would expand it   REFUSE
extends:                     image or build may come from elsewhere    REFUSE
neither image: nor build:    no artefact for a derived name to name    REFUSE
```
"""
from __future__ import annotations

import argparse
import json
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


def _usable(ref: object) -> bool:
    """Is this a reference docker could actually resolve?

    Checked on BOTH branches, because the authoritative one has its own way of
    producing a confident non-answer: Compose interpolates an UNSET variable to
    the empty string, so `image: thing:${TAG}` renders as `thing:` — a
    malformed reference that is not empty, not obviously wrong, and would be
    written into the manifest as the name of an artefact.

    Narrow on purpose. This is not image-reference validation; it rejects the
    two shapes that mean a substitution went missing.
    """
    if not isinstance(ref, str):
        return False
    ref = ref.strip()
    if not ref or "${" in ref:
        return False
    # An empty tag or an empty repository — `thing:` or `:1.2.3`.
    tag = ref.rsplit("/", 1)[-1]
    if tag.startswith(":") or tag.endswith(":"):
        return False
    return True


def _from_parsed_yaml(compose_file: str, service: str) -> tuple[str | None, str]:
    """Resolve from the file itself, in the SAME order, or say why not.

    Returns `(ref, reason)`. `ref` is None whenever the file does not settle
    the question; `reason` then names what was missing, because "could not
    resolve" without a cause sends the operator to the wrong file.
    """
    try:
        import yaml
    except ImportError:
        return None, ("PyYAML is not available, so an explicit `image:` cannot "
                      "be attributed to a service. A derived <project>-<service> "
                      "name would be a guess about which of the two applies")
    try:
        doc = yaml.safe_load(Path(compose_file).read_text())
    except Exception as exc:                                 # noqa: BLE001
        return None, f"{compose_file} could not be parsed as YAML: {exc}"
    if not isinstance(doc, dict):
        return None, f"{compose_file} is not a compose document"

    services = doc.get("services")
    if not isinstance(services, dict) or service not in services:
        # ABSENT IS NOT "HAS NO EXPLICIT IMAGE". Deriving a name here would
        # invent an artefact for a service this file does not define — which is
        # how a manifest ends up naming something nobody ran.
        return None, (f"{compose_file} defines no service {service!r}, so "
                      f"nothing in it says which image that service uses")

    svc = services.get(service) or {}
    if not isinstance(svc, dict):
        return None, f"service {service!r} is not a mapping"

    if "extends" in svc:
        # `extends` can carry `image` or `build` in from another file. Compose
        # merges it; reading this file alone cannot.
        return None, (f"service {service!r} uses `extends`, so its image may be "
                      f"declared in another file this parser is not reading")

    explicit = svc.get("image")
    if explicit:
        if not _usable(explicit):
            # Compose would interpolate this from the environment. Returning
            # the literal would name an image whose tag is the variable itself.
            return None, (f"service {service!r} declares image {explicit!r}, "
                          f"which needs environment interpolation only Compose "
                          f"can perform")
        return str(explicit), "explicit image:"

    if "build" not in svc:
        # Nothing to build and nothing declared: there is no artefact for a
        # derived name to refer to.
        return None, (f"service {service!r} declares neither `image:` nor "
                      f"`build:`, so no image of its own exists to name")

    project = doc.get("name")
    if not project:
        return None, (f"{compose_file} declares no top-level `name:`, so the "
                      f"project prefix Compose would use is unknown")
    return f"{project}-{service}", "derived <project>-<service>"


def resolve(compose_file: str, service: str) -> str | None:
    """The image reference Compose will use, or None. NEVER a guess."""
    cfg = _compose_json(compose_file)
    services = (cfg or {}).get("services") or {}
    # ONLY when the rendered model actually CONTAINS the service. A PROFILE-
    # GATED service is omitted from `docker compose config` unless its profile
    # is activated, and taking its absence as "declares no image" reproduces
    # the fallback's bug on the preferred branch. It is not hypothetical:
    # `docker-compose.sentinel.yml` puts the `sentinel` service behind
    # `profiles: ["cli"]` and declares `image: sentinel:latest`, and this
    # derived `sentinel-sentinel` for it — a name for an artefact that has one.
    if service in services:
        svc = services[service] or {}
        explicit = svc.get("image")
        if explicit:
            # A rendered image is still checked: an unset variable interpolates
            # to nothing and leaves a malformed ref that reads as an answer.
            return explicit if _usable(explicit) else None
        project = (cfg or {}).get("name")
        if project:
            derived = f"{project}-{service}"
            return derived if _usable(derived) else None
    # Compose could not be run (no daemon, not installed, not this machine), or
    # it ran and the service was profile-gated out of the result. The file still
    # answers, and it must be asked in the SAME order — an explicit image first.
    # The version of this fallback that read only the top-level `name:` skipped
    # straight to the derived name and so returned a derived name for services
    # that had declared their image outright.
    return _from_parsed_yaml(compose_file, service)[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True)
    ap.add_argument("--service", required=True)
    args = ap.parse_args(list(argv or sys.argv[1:]))
    ref = resolve(args.file, args.service)
    if not ref:
        # NAME THE CAUSE. "Could not resolve" alone sends the operator to the
        # compose file when the actual problem may be a missing parser or an
        # uninterpolated variable.
        _, why = _from_parsed_yaml(args.file, args.service)
        print(f"REFUSED: could not resolve the image for {args.service!r} in "
              f"{args.file}.\n  {why}.\n"
              f"  Not guessed: a wrong image name that RESOLVES is worse than "
              f"one that does not, because the record would then name an "
              f"artefact nobody ran.", file=sys.stderr)
        return 1
    sys.stdout.write(ref)
    return 0


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
