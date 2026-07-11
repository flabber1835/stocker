"""Image-layout import smoke — catches container-only import failures in CI.

THE BUG CLASS: a service imports fine from the repo checkout (so every unit test
stays green) but dies inside its image because the image's directory layout
differs — observed with bt-engine's app/live loader computing
Path(__file__).parents[3] at import time: 4 parents exist under
services/bt-engine/app/live, only 3 under the image's /app/app/live → IndexError
→ container crash-loop, discovered only at deploy.

THE GUARD: for each service whose image assembles code with build-time COPY
tricks, parse its Dockerfile's COPY directives, reconstruct the image's exact
filesystem under a shallow temp WORKDIR (same depth as /app), and `import
app.main` in a FRESH interpreter (subprocess — mimics uvicorn's import, immune
to this pytest process's module cache). Dockerfile changes are picked up
automatically since the layout is derived from the Dockerfile itself.

Companion for deploy hosts: scripts/smoke-image-imports.sh does the same against
the REAL built images (requires Docker).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Services with multi-source / layout-sensitive image builds. Adding a service
# here is one line; env is whatever its module-level import requires.
SERVICES = {
    "bt-engine": {},
    "bt-data": {},
    "bt-scheduler": {},
    "backtester": {},   # checked-in _vendor — plain copy, guarded cheaply anyway
    "evaluator": {},    # checked-in _vendor + runtime /repo mounts
}

_DUMMY_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://smoke:smoke@localhost/smoke",
    "BT_DATABASE_URL": "postgresql+asyncpg://smoke:smoke@localhost/smoke",
    "ALPACA_API_KEY": "", "AV_API_KEY": "demo",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def parse_copy_directives(dockerfile: Path) -> list[tuple[list[str], str]]:
    """[(source_paths_relative_to_repo, dest_relative_to_WORKDIR)] from COPY
    lines, with backslash line-continuations joined. --from= stages skipped."""
    raw = dockerfile.read_text()
    # join continuations
    joined = raw.replace("\\\n", " ")
    out = []
    for line in joined.splitlines():
        line = line.strip()
        if not line.upper().startswith("COPY ") or "--from=" in line:
            continue
        parts = line.split()[1:]
        srcs, dest = parts[:-1], parts[-1]
        out.append((srcs, dest))
    return out


def materialize_image_layout(service: str, workdir: Path) -> None:
    """Replicate the image's /app content under `workdir` (depth-faithful)."""
    dockerfile = REPO / "services" / service / "Dockerfile"
    for srcs, dest in parse_copy_directives(dockerfile):
        dest_path = workdir / dest.lstrip("./")
        for src in srcs:
            src_path = REPO / src
            if not src_path.exists():
                raise AssertionError(f"{service}: Dockerfile COPY source missing: {src}")
            if src_path.is_dir():
                target = dest_path if dest.endswith("/") or dest in (".", "./") else dest_path
                shutil.copytree(src_path, target, dirs_exist_ok=True)
            else:
                # docker semantics: dest ending in / (or existing dir) = directory
                if dest.endswith("/") or dest in (".", "./"):
                    dest_dir = workdir / dest.lstrip("./")
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_path, dest_dir / src_path.name)
                else:
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_path, dest_path)


import re


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_no_checkout_depth_path_arithmetic(service):
    """Static twin of the import test, exact and environment-independent: for
    every file the image ships, any Path(...).parents[N] must resolve at the
    file's IN-IMAGE depth (rooted at /app), not its repo-checkout depth. This is
    precisely the bt-engine bug (parents[3] fine at services/bt-engine/app/live,
    IndexError at /app/app/live)."""
    with tempfile.TemporaryDirectory(prefix=f"smoke-{service}-") as td:
        workdir = Path(td)
        materialize_image_layout(service, workdir)
        offenders = []
        for f in workdir.rglob("*.py"):
            text = f.read_text(errors="replace")
            lines = text.splitlines()
            for m in re.finditer(r"\.parents\[(\d+)\]", text):
                idx = int(m.group(1))
                # in-image dir of this file: /app/<rel-dir> → its parents count
                rel_dir = f.parent.relative_to(workdir)
                in_image_dir = Path("/app") / rel_dir
                available = len(in_image_dir.parents)   # e.g. /app/app/live → 3
                if idx < available:
                    continue
                # GUARDED usage is fine: `except IndexError` within the next few
                # lines (the canonical shallow-image fallback pattern).
                line_no = text[:m.start()].count("\n")
                lookahead = "\n".join(lines[line_no:line_no + 4])
                if "IndexError" in lookahead:
                    continue
                offenders.append(f"{rel_dir}/{f.name}: parents[{idx}] but only "
                                 f"{available} parents exist at {in_image_dir} "
                                 f"(guard with try/except IndexError)")
        assert not offenders, (
            f"{service}: checkout-depth path arithmetic would crash in the image:\n"
            + "\n".join(offenders))


def _shallow_workdir(service: str):
    """A workdir whose depth MATCHES the image's /app when possible (a root-level
    dir — needs a writable /, true in containers/CI). Falls back to /tmp/<uniq>
    (one level deeper — the static test above still guards the depth class)."""
    if os.access("/", os.W_OK):
        d = Path(f"/smoke-{service}-{os.getpid()}")
        d.mkdir(exist_ok=True)
        return d, True
    return Path(tempfile.mkdtemp(prefix=f"smoke-{service}-")), False


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_app_main_imports_under_image_layout(service):
    workdir, depth_exact = _shallow_workdir(service)
    try:
        materialize_image_layout(service, workdir)
        assert (workdir / "app" / "main.py").exists(), \
            f"{service}: image layout has no app/main.py — Dockerfile changed?"
        env = {**os.environ, **_DUMMY_ENV, **SERVICES[service],
               "PYTHONPATH": f"{REPO / 'shared'}{os.pathsep}{workdir}"}
        proc = subprocess.run(
            [sys.executable, "-c", "import app.main"],
            cwd=workdir, env=env, capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, (
            f"{service}: `import app.main` FAILED under the image layout"
            f"{' (depth-exact)' if depth_exact else ''} — this container would "
            f"crash-loop in production.\n--- stderr ---\n{proc.stderr[-3000:]}"
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
