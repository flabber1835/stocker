"""`scripts/sentinel-env-from-stocker.py` — the whitelist, and the silence.

Two properties carry real weight here and neither is visible by reading the
output of a successful run:

  * it must never print a VALUE. This runs on a NAS over SSH, and a terminal
    that has echoed a Sharadar key has put it in scrollback, in the history of
    anyone who scrolled, and in any transcript of the session;
  * it must drop by WHITELIST, so a variable nobody thought about is dropped by
    construction rather than by somebody remembering to.

The rest is round-tripping, because a `.env` that parses differently from how
it was written is a credential that silently is not the credential.
"""
from __future__ import annotations

import importlib.util
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or ROOT)
SCRIPT = REPO / "scripts" / "sentinel-env-from-stocker.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("env_from_stocker", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


#: A Stocker `.env` with one of every hazard, and values distinctive enough
#: that a leak cannot be mistaken for anything else.
OLD = """\
AV_API_KEY=LEAKCANARY_AV
ALPACA_API_KEY=LEAKCANARY_ALPACA
ALPACA_SECRET_KEY=LEAKCANARY_SECRET
ALPACA_BASE_URL=https://api.alpaca.markets
SHARADAR_API_KEY=LEAKCANARY_SHARADAR
SHARADAR_FETCH_RETRIES=5
PAPER_ONLY=true
LIVE_TRADING_ENABLED=false
KILL_SWITCH=false
MAX_ORDER_NOTIONAL=50000.0
ANTHROPIC_API_KEY=LEAKCANARY_ANTHROPIC
export IBKR_PASSWORD=LEAKCANARY_IBKR
TAVILY_API_KEY=
STRATEGY_CONFIG_PATH=/strategies/x.yaml   # NOT CONSUMED
"""

CANARIES = [w for w in re.findall(r"LEAKCANARY_\w+", OLD)]


def run(tmp_path, body=OLD, *extra):
    src = tmp_path / "old.env"
    src.write_text(body)
    dst = tmp_path / "new.env"
    r = subprocess.run([sys.executable, str(SCRIPT), "--from", str(src),
                        "--to", str(dst), *extra],
                       capture_output=True, text=True)
    return r, dst


class TestItNeverPrintsAValue:
    def test_no_canary_reaches_stdout_or_stderr(self, tmp_path):
        r, _ = run(tmp_path)
        assert r.returncode == 0, r.stderr
        blob = r.stdout + r.stderr
        leaked = [c for c in CANARIES if c in blob]
        assert not leaked, (
            f"the report echoed credential values: {leaked}. On a NAS over SSH "
            f"that puts them in scrollback and in the session transcript.")

    def test_the_canaries_are_REAL(self, tmp_path):
        """Guard the guard. If the fixture stopped containing distinctive
        values, the assertion above would pass for every implementation."""
        assert len(CANARIES) >= 5
        _, dst = run(tmp_path)
        written = dst.read_text()
        assert "LEAKCANARY_SHARADAR" in written, (
            "the key was not written at all — the leak test is vacuous")

    def test_it_leaks_nothing_on_the_REFUSAL_path_either(self, tmp_path):
        """An error message is the likeliest place to interpolate the value
        that caused it."""
        r, _ = run(tmp_path, "ALPACA_API_KEY=LEAKCANARY_ALPACA\n")
        assert r.returncode == 1
        assert "LEAKCANARY_ALPACA" not in r.stdout + r.stderr


class TestTheWhitelist:
    def test_only_whitelisted_variables_are_written(self, tmp_path, mod):
        _, dst = run(tmp_path)
        got = set(mod.parse_env(dst))
        allowed = set(mod.CARRY) | set(mod.GENERATE) | set(mod.FORCED)
        assert got <= allowed, got - allowed

    def test_the_retired_credentials_are_GONE(self, tmp_path, mod):
        """Asserted against the PARSED variables, not the raw text. The header
        comment names some of these while explaining why they were dropped, so
        a substring check would be satisfied by the explanation instead of the
        behaviour — the same trap as the `fetchall()` test that matched its own
        docstring, which this repository has now hit three times."""
        got = set(mod.parse_env(dst := run(tmp_path)[1]))
        assert dst.exists()
        for dead in ("AV_API_KEY", "ANTHROPIC_API_KEY", "IBKR_PASSWORD",
                     "STRATEGY_CONFIG_PATH", "TAVILY_API_KEY"):
            assert dead not in got, f"{dead} was carried forward"

    def test_the_INERT_safety_flags_are_dropped_and_NAMED(self, tmp_path, mod):
        """Dropping them silently would be worse than carrying them: somebody
        who believed PAPER_ONLY was protecting them needs to be told it was
        not, and where the real guard lives."""
        r, dst = run(tmp_path)
        assert not (set(mod.parse_env(dst)) & mod.INERT_SAFETY)
        assert "PAPER_ONLY" in r.stdout
        assert "LIVE_HOSTS" in r.stdout

    def test_the_live_endpoint_is_never_inherited(self, tmp_path, mod):
        r, dst = run(tmp_path)
        assert mod.parse_env(dst)["ALPACA_BASE_URL"] == \
            "https://paper-api.alpaca.markets"
        assert "LIVE host" in r.stdout, (
            "the old deployment pointed at real money and the report said "
            "nothing")

    def test_every_carried_name_is_read_by_the_SOURCE(self, mod):
        """The whitelist is only correct while the code still reads these. A
        name that no longer appears anywhere is a variable being propagated
        because it once mattered.

        The haystack covers the production runtime and its operator entrypoint.
        """
        hay = "\n".join(
            p.read_text() for p in (REPO / "sentinel").rglob("*.py"))
        for extra in ("docker-compose.sentinel.yml",
                      "scripts/sentinel-certify.sh"):
            hay += (REPO / extra).read_text()
        orphans = [k for k in set(mod.CARRY) | set(mod.GENERATE)
                   if k not in hay]
        assert not orphans, (
            f"{orphans} are carried forward but nothing reads them")

class TestTheOutputIsFAITHFUL:
    HARD = ("SHARADAR_API_KEY=plain123\n"
            "ALPACA_API_KEY=has$dollar\n"
            "ALPACA_SECRET_KEY=hash#inside\n")

    def test_values_round_trip_through_the_parser(self, tmp_path, mod):
        _, dst = run(tmp_path, self.HARD)
        got = mod.parse_env(dst)
        assert got["ALPACA_API_KEY"] == "has$dollar"
        assert got["ALPACA_SECRET_KEY"] == "hash#inside"

    def test_values_round_trip_through_SOURCE(self, tmp_path):
        """Unquoted was the first version, and `pa ss@word` came out of it:
        legal to compose, fatal to `source`, and `$dollar` silently expanded
        to nothing."""
        _, dst = run(tmp_path, self.HARD)
        r = subprocess.run(
            ["bash", "-c",
             f'set -a; . "{dst}"; set +a; '
             f'printf "%s|%s" "$ALPACA_API_KEY" "$ALPACA_SECRET_KEY"'],
            capture_output=True, text=True)
        assert r.stdout == "has$dollar|hash#inside", r.stdout

    def test_it_WARNS_about_a_literal_dollar(self, tmp_path):
        r, _ = run(tmp_path, self.HARD)
        assert "literal '$'" in r.stdout


class TestItFailsClosed:
    def test_a_missing_sharadar_key_REFUSES(self, tmp_path):
        r, dst = run(tmp_path, "ALPACA_API_KEY=x\n")
        assert r.returncode == 1
        assert not dst.exists()

    def test_a_PLACEHOLDER_sharadar_key_refuses(self, tmp_path):
        """The old `.env.example` ships `your_..._here`. A file copied from it
        and never filled in would otherwise pass and die hours later."""
        r, _ = run(tmp_path, "SHARADAR_API_KEY=your_sharadar_key_here\n")
        assert r.returncode == 1

    def test_it_will_not_clobber_an_existing_env(self, tmp_path):
        src = tmp_path / "old.env"
        src.write_text(OLD)
        dst = tmp_path / "new.env"
        dst.write_text("SENTINEL_POSTGRES_PASSWORD=theOneInUse\n")
        r = subprocess.run([sys.executable, str(SCRIPT), "--from", str(src),
                            "--to", str(dst)], capture_output=True, text=True)
        assert r.returncode == 2
        assert dst.read_text() == "SENTINEL_POSTGRES_PASSWORD=theOneInUse\n"

    def test_dry_run_writes_NOTHING(self, tmp_path):
        r, dst = run(tmp_path, OLD, "--dry-run")
        assert r.returncode == 0
        assert not dst.exists()

    def test_the_file_is_0600(self, tmp_path):
        _, dst = run(tmp_path)
        assert stat.S_IMODE(dst.stat().st_mode) == 0o600

    def test_a_generated_password_is_DSN_safe(self, tmp_path, mod):
        """It is spliced into `postgresql://sentinel:${...}@host:5432/db`. Any
        of :/@?# ends it early or moves the host, and the error names a
        connection rather than a password."""
        for _ in range(20):
            _, dst = run(tmp_path, OLD, "--force")
            pw = mod.parse_env(dst)["SENTINEL_POSTGRES_PASSWORD"]
            assert len(pw) >= 24
            assert not (set(pw) & mod._DSN_HOSTILE), pw
            assert "$" not in pw

    def test_two_runs_do_not_produce_the_SAME_password(self, tmp_path):
        _, d1 = run(tmp_path)
        seen = d1.read_text()
        _, d2 = run(tmp_path, OLD, "--force")
        assert d2.read_text() != seen


class TestItRunsOnTheHostInterpreter:
    """It cannot run inside the 3.12 image, so it cannot assume 3.12.

    This script produces the `.env` that compose reads, which means it runs
    BEFORE any image exists — on whatever python3 the NAS ships. The first real
    invocation died on `str.removeprefix`, which is 3.9+, with an
    AttributeError three lines into parsing. Nothing here caught it because
    every check ran on this repository's 3.12.

    `scripts/sentinel-measure.sh` has the same exposure: it is host-side too,
    and its inline python blocks are checked below for the same reason.
    """

    FLOOR = (3, 7)

    #: Names that exist only above the floor and would raise at RUN time, so a
    #: syntax check cannot see them. Extended when one bites, which is how
    #: `removeprefix` got here.
    GATED = {
        "removeprefix": (3, 9), "removesuffix": (3, 9),
        "itertools.pairwise": (3, 10), "graphlib": (3, 9),
        "zoneinfo": (3, 9), "tomllib": (3, 11),
        "functools.cache": (3, 9), "ExceptionGroup": (3, 11),
    }

    MEASURE = REPO / "scripts" / "sentinel-measure.sh"

    def host_python_sources(self):
        """(label, source) for every python that runs on the HOST."""
        import re as _re
        out = [(SCRIPT.name, SCRIPT.read_text())]
        sh = self.MEASURE.read_text()
        for i, code in enumerate(_re.findall(r"<<'PY'\n(.*?)\nPY\b", sh, _re.S)):
            out.append((f"{self.MEASURE.name}:heredoc{i}", code))
        inline = r'(?:python3|"\$\{HOST_PYTHON\}") -c \'\n(.*?)\n\''
        for i, code in enumerate(_re.findall(inline, sh, _re.S)):
            out.append((f"{self.MEASURE.name}:inline{i}", code))
        return out

    def test_the_scan_finds_the_blocks(self):
        """Guard the guard: a regex that matched nothing would pass every
        assertion below."""
        got = self.host_python_sources()
        assert len(got) >= 4, [n for n, _ in got]

    def test_measurement_uses_the_selected_compatible_host_python(self):
        body = self.MEASURE.read_text()
        assert 'HOST_PYTHON="${SENTINEL_HOST_PYTHON:-python3}"' in body
        assert "scripts/sentinel_host_python.py" in body
        assert body.index("scripts/sentinel_host_python.py") \
            < body.index("docker image inspect")
        executable = "\n".join(
            line for line in body.splitlines()
            if not line.lstrip().startswith("#")
        )
        assert not __import__("re").search(r"(^|[|;&(]\s*)python3\s", executable)

    def test_the_SYNTAX_parses_at_the_floor(self):
        import ast
        bad = []
        for name, code in self.host_python_sources():
            try:
                ast.parse(code, feature_version=self.FLOOR)
            except SyntaxError as e:
                bad.append(f"{name}: {e}")
        assert not bad, (
            f"host-side python must parse on {self.FLOOR}: {bad}")

    def test_no_METHOD_newer_than_the_floor_is_CALLED(self):
        """Syntax parsing cannot see these — `s.removeprefix(x)` is valid
        syntax on 3.7 and an AttributeError at run time."""
        bad = []
        for name, code in self.host_python_sources():
            # Comments are stripped: the fix for removeprefix NAMES it while
            # explaining why it is not used, and a substring check would fire
            # on the explanation. Same trap as the fetchall() docstring.
            body = "\n".join(l.split("#", 1)[0] for l in code.splitlines())
            for gated, ver in self.GATED.items():
                needle = gated if "." in gated else f".{gated}("
                if needle in body:
                    bad.append(f"{name}: {gated} needs {ver[0]}.{ver[1]}")
        assert not bad, bad

    def test_the_gated_list_would_actually_MATCH(self):
        """The scan strips comments and looks for `.name(`. If that shape were
        wrong the check would be silently empty forever."""
        probe = "x = s.removeprefix('a')\n"
        assert ".removeprefix(" in probe
        commented = "# do not use s.removeprefix('a')\n"
        assert ".removeprefix(" not in \
            "\n".join(l.split("#", 1)[0] for l in commented.splitlines())

    def test_it_REFUSES_clearly_below_the_floor(self, mod):
        """Rather than dying on whatever construct happens to be first."""
        body = SCRIPT.read_text()
        assert "MIN_PYTHON" in body
        assert mod.MIN_PYTHON == self.FLOOR
        assert "sys.version_info < MIN_PYTHON" in body
        # The message has to say what to DO. "REFUSED" alone strands somebody
        # on a NAS whose default python3 is old but which has a newer one.
        assert "python3.11" in body or "newer python3" in body


class TestTheWhitelistIsCOMPLETEAgainstCompose:
    """Every production compose variable must have an explicit disposition."""

    COMPOSE = ("docker-compose.sentinel.yml",)

    def referenced(self):
        import re as _re
        out = {}
        for f in self.COMPOSE:
            body = (REPO / f).read_text()
            live = "\n".join(l for l in body.splitlines()
                             if not l.strip().startswith("#"))
            for v in _re.findall(r"\$\{([A-Z_][A-Z_0-9]*)", live):
                out.setdefault(v, f)
        return out

    def test_the_scan_finds_the_production_file(self):
        """Guard the guard: a regex matching nothing passes vacuously."""
        got = self.referenced()
        assert "SHARADAR_API_KEY" in got
        # The active Sentinel compose deliberately uses the literal
        # ``sentinel:latest`` convenience alias; image identity is verified by
        # digest instead of a fifteenth interpolated environment variable.
        # Keep this as a non-vacuity floor while the classification test below
        # remains the authoritative complete-set guard.
        assert len(got) >= 14, sorted(got)

    def test_every_composed_variable_is_CLASSIFIED(self):
        mod_ns = {}
        import importlib.util
        spec = importlib.util.spec_from_file_location("efs", SCRIPT)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        known = (set(m.CARRY) | set(m.GENERATE) | set(m.FORCED)
                 | set(m.DELIBERATELY_UNSET) | m.INERT_SAFETY)
        unclassified = {v: f for v, f in self.referenced().items()
                        if v not in known}
        assert not unclassified, (
            "these are read by a compose file and the whitelist has never "
            f"decided about them, so they are dropped by accident: "
            f"{unclassified}. Add each to CARRY or to DELIBERATELY_UNSET with "
            f"a reason.")

    def test_the_deliberate_omissions_each_carry_a_REASON(self, mod):
        empty = [k for k, v in mod.DELIBERATELY_UNSET.items()
                 if not v or len(v) < 15]
        assert not empty, f"no stated reason for: {empty}"

    def test_workflow_selected_identities_are_never_carried(self, mod):
        expected_owner = {
            "SENTINEL_RUNTIME_IMAGE_REF": "deployment/promotion workflow",
        }
        for name, owner in expected_owner.items():
            assert name in mod.DELIBERATELY_UNSET
            assert name not in mod.CARRY
            reason = mod.DELIBERATELY_UNSET[name]
            assert owner in reason
            assert "stale" in reason
