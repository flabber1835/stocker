"""Which image does Compose build? The two scripts must not each have a theory.

The certification harness freezes the bt-engine image into the manifest; the
launcher injects its id so every run records what produced it. Both needed the
image's name, and both had their own copy of the same inference:

```text
$(basename "$(pwd)")-bt-engine        ->  stocker-bt-engine
```

`docker-compose.backtest.yml` declares `name: stocker-bt`, and Compose uses the
top-level `name:` as the PROJECT ahead of the directory basename, so the image
it actually builds is `stocker-bt-bt-engine`. The guess never resolves.

That fails closed, which is why it is worth a test rather than a shrug: the
first thing it stops is the bootstrap build, several steps before the 2b lock
refusal that build exists to demonstrate. And the deeper defect is not the
wrong string — it is that TWO scripts each held an opinion about which artefact
they meant. A manifest freezing one image while the launcher starts another is
the same class of defect one level up, and it would not fail closed at all.

So the inference is gone and the resolver is shared. The falsifier below is the
one the directory basename cannot survive: a project name that is deliberately
NOT the directory's.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or ROOT)
RESOLVER = ROOT / "scripts" / "compose_image.py"
CERTIFY = REPO / "scripts" / "sentinel-certify.sh"
LAUNCHER = REPO / "scripts" / "bt-engine-up.sh"

sys.path.insert(0, str(RESOLVER.parent))
import compose_image  # noqa: E402


#: The project name that makes the old inference wrong in a way it cannot
#: accidentally get right. Any test that passes with this in place is reading
#: the file, not the directory it happens to sit in.
FALSIFIER_PROJECT = "definitely-not-the-directory-name"

FALSIFIER_YAML = f"""\
name: {FALSIFIER_PROJECT}

services:
  bt-engine:
    build:
      context: .
      dockerfile: services/bt-engine/Dockerfile
    environment:
      BT_ENGINE_IMAGE_ID: ${{BT_ENGINE_IMAGE_ID:-}}
"""


@pytest.fixture()
def falsifier(tmp_path: Path) -> Path:
    p = tmp_path / "docker-compose.falsifier.yml"
    p.write_text(FALSIFIER_YAML)
    return p


def run_resolver(compose_file: Path, service: str = "bt-engine"):
    """Invoke the resolver exactly as the shell scripts do."""
    return subprocess.run(
        [sys.executable, str(RESOLVER), "--file", str(compose_file),
         "--service", service],
        capture_output=True, text=True, cwd=str(ROOT))


# ── 1. the falsifier: the project name is not the directory name ─────────────

class TestTheProjectNameBeatsTheDirectory:

    def test_the_resolver_reads_the_file_not_the_directory(self, falsifier):
        assert compose_image.resolve(str(falsifier), "bt-engine") == \
            f"{FALSIFIER_PROJECT}-bt-engine"

    def test_the_old_inference_would_have_disagreed(self, falsifier):
        """The falsifier's whole job: show the two answers differ.

        Without this the test could be satisfied by a directory that happens to
        be named after the project — which is exactly the coincidence that let
        the guess look correct everywhere except the one file that matters.
        """
        guess = f"{Path.cwd().name}-bt-engine"
        resolved = compose_image.resolve(str(falsifier), "bt-engine")
        assert resolved != guess
        assert resolved == f"{FALSIFIER_PROJECT}-bt-engine"

    def test_both_scripts_get_the_SAME_answer(self, falsifier):
        """Run the resolver the way each script runs it, on the same file.

        The point is not that one command is repeated. It is that there is only
        ONE implementation to repeat, so the harness and the launcher cannot
        drift apart no matter which is edited.
        """
        a = run_resolver(falsifier)
        b = run_resolver(falsifier)
        assert a.returncode == 0, a.stderr
        assert b.returncode == 0, b.stderr
        assert a.stdout == b.stdout == f"{FALSIFIER_PROJECT}-bt-engine"


# ── 2. the real file, which is where the bug actually lived ──────────────────

class TestTheRealBacktestCompose:

    def test_it_declares_a_project_name_unlike_the_directory(self):
        """Guard the premise. If `name:` is ever dropped from the compose file
        the resolver still works, but this repo stops being a live example of
        the trap and the falsifier above becomes the only cover."""
        assert "\nname: stocker-bt\n" in \
            (REPO / "docker-compose.backtest.yml").read_text()

    def test_the_resolved_image_is_the_double_prefixed_one(self):
        assert compose_image.resolve(
            str(REPO / "docker-compose.backtest.yml"), "bt-engine") == \
            "stocker-bt-bt-engine"

    def test_which_is_NOT_what_the_basename_guess_produced(self):
        assert compose_image.resolve(
            str(REPO / "docker-compose.backtest.yml"),
            "bt-engine") != "stocker-bt-engine"


# ── 3. explicit beats derived, and neither beats refusing ────────────────────

class TestResolutionOrder:

    def test_an_explicit_image_wins(self, tmp_path: Path):
        p = tmp_path / "c.yml"
        p.write_text("name: someproject\nservices:\n  svc:\n"
                     "    image: ghcr.io/example/thing:1.2.3\n")
        assert compose_image.resolve(str(p), "svc") == \
            "ghcr.io/example/thing:1.2.3"

    def test_no_project_name_and_no_image_REFUSES(self, tmp_path: Path):
        """Never a guess.

        A wrong image name that RESOLVES is worse than one that does not: the
        manifest would name an artefact nobody ran, and every later comparison
        against it would pass. Refusing costs a rerun; guessing costs the
        meaning of the record.
        """
        p = tmp_path / "c.yml"
        p.write_text("services:\n  svc:\n    build: .\n")
        # `docker compose config` can still supply a project name from the
        # directory when it runs, so only the no-Compose path is asserted here
        # — that is the path this fallback exists for.
        assert compose_image._project_name_from_yaml(str(p)) is None

    def test_the_cli_exits_nonzero_and_prints_nothing_on_refusal(self,
                                                                tmp_path):
        p = tmp_path / "nonexistent-compose.yml"
        r = run_resolver(p, "svc")
        assert r.returncode != 0
        assert r.stdout == ""
        assert "REFUSED" in r.stderr

    def test_a_commented_out_name_is_not_read_as_the_project(self,
                                                            tmp_path: Path):
        p = tmp_path / "c.yml"
        p.write_text("# name: looks-like-a-name\nservices:\n  svc:\n"
                     "    build: .\n")
        assert compose_image._project_name_from_yaml(str(p)) is None

    def test_an_indented_name_key_is_not_the_top_level_project(self,
                                                               tmp_path: Path):
        """`name:` nested under a service is a different key entirely."""
        p = tmp_path / "c.yml"
        p.write_text("services:\n  svc:\n    name: not-the-project\n"
                     "    build: .\n")
        assert compose_image._project_name_from_yaml(str(p)) is None


# ── 4. both scripts actually USE it ──────────────────────────────────────────

class TestTheScriptsDelegate:

    @pytest.mark.parametrize("script", [CERTIFY, LAUNCHER],
                             ids=["certify", "launcher"])
    def test_the_script_calls_the_shared_resolver(self, script: Path):
        body = script.read_text()
        assert "scripts/compose_image.py" in body
        assert "--file docker-compose.backtest.yml --service bt-engine" in \
            body.replace("\\\n", "").replace("  ", " ")

    @pytest.mark.parametrize("script", [CERTIFY, LAUNCHER],
                             ids=["certify", "launcher"])
    def test_no_basename_inference_survives(self, script: Path):
        """The specific construct that was wrong, in either spelling."""
        executable = "\n".join(
            l for l in script.read_text().splitlines()
            if not l.lstrip().startswith("#"))
        assert "basename" not in executable
        assert "stocker-bt-engine" not in executable

    @pytest.mark.parametrize("script", [CERTIFY, LAUNCHER],
                             ids=["certify", "launcher"])
    def test_an_unresolvable_image_stops_the_script(self, script: Path):
        """Resolution failure must not fall through to a default.

        Both call sites wrap the resolver in a failure branch; a bare
        substitution would leave an empty ref and the next docker command would
        report something unrelated.
        """
        body = script.read_text()
        i = body.index("compose_image.py")
        window = body[i:i + 600]
        assert ("fail " in window) or ("exit 1" in window)
