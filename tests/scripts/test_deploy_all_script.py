"""scripts/deploy-all.sh — the "I don't know what's deployed" command.

Its whole value is that you can run it without reasoning about what changed. So
the properties worth asserting are about ORDER and COVERAGE: base before
services, git before build, both stacks, and a verification step that would
actually notice a half-deployed system.

Static assertions — the script drives docker and a live NAS, neither of which
belongs in a unit test. What can be checked here is that it cannot be silently
wrong in the ways this repo has already been bitten by.
"""
import os
import re
import subprocess

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SCRIPT = os.path.join(ROOT, "scripts", "deploy-all.sh")
UP = os.path.join(ROOT, "scripts", "up.sh")


@pytest.fixture(scope="module")
def src():
    with open(SCRIPT) as f:
        return f.read()


@pytest.fixture(scope="module")
def code(src):
    """The script with COMMENT lines stripped.

    Ordering and hardcoded-value assertions must read the executable text: the
    header comment names every stage in prose, so `src.index("scripts/up.sh")`
    finds the documentation, not the call. The first draft of this test failed
    for exactly that reason on three assertions."""
    return "\n".join(ln for ln in src.splitlines()
                      if not ln.lstrip().startswith("#"))


def test_exists_and_is_executable():
    assert os.path.isfile(SCRIPT) and os.access(SCRIPT, os.X_OK)


def test_bash_syntax_is_valid():
    subprocess.run(["bash", "-n", SCRIPT], check=True)


# ── ordering: the part that is easy to get wrong and silent when wrong ──────

def test_base_is_built_before_the_stacks(code):
    """17 service images are FROM stocker-base. Building services first means
    they bake yesterday's shared/ — the failure this command exists to end."""
    assert code.index("Dockerfile.base") < code.index("scripts/up.sh")


def test_git_sync_precedes_any_build(code):
    """Building before syncing deploys code that is not what HEAD says it is."""
    assert code.index("scripts/deploy.sh") < code.index("Dockerfile.base")


def test_a_failed_git_sync_aborts_rather_than_deploying_stale_code(code):
    block = code[code.index("scripts/deploy.sh"):code.index("Dockerfile.base")]
    assert "exit 1" in block


def test_the_base_rebuild_is_unconditional(src):
    """up.sh uses a staleness HEURISTIC; this command promises certainty. If the
    base build here were conditional the promise would be a guess."""
    build = src[src.index("2/4"):src.index("3/4")]
    assert "docker image inspect" not in build, (
        "the all-encompassing deploy must not skip the base rebuild")


def test_both_stacks_are_deployed(src):
    """A live-only deploy is how the two stacks drifted apart in the first place."""
    assert "scripts/up.sh --build" in src


def test_the_in_flight_guard_is_not_bypassed_by_default(src):
    """Recreating bt-engine mid-sweep destroys the sweep (it marks its own rows
    RESTART_ABORTED on startup). --force must be opt-in."""
    assert "--force" in src
    default_call = re.search(r'else\s*\n\s*scripts/up\.sh --build(?! --force)', src)
    assert default_call, "the default path must call up.sh WITHOUT --force"


# ── verification: it must be able to notice a bad deploy ────────────────────

def test_ports_are_asked_of_compose_not_hardcoded(code):
    """The first draft hardcoded ports and had five wrong. A health probe on the
    wrong port reports a healthy service as down — or another service as healthy."""
    assert "docker compose" in code and 'port "$svc" 8000' in code
    # No literal host port may appear in a health URL in the EXECUTABLE text.
    assert not re.search(r'localhost:\d{4}/health', code), \
        "a hardcoded health port is back — ask compose instead"


def test_the_gate_probe_has_no_side_effects(code):
    """THE bug this replaced. The first version POSTed a real /jobs/run and read
    the status code — fine while the active config was guaranteed to be REFUSED,
    but the moment SUE parity made it scorable the same probe STARTED A BACKTEST,
    from --verify, whose contract is that it changes nothing."""
    assert "/gates/check" in code, "the gate probe must be the read-only endpoint"
    assert "POST http://localhost:8031/jobs/run" not in code
    assert "-X POST" not in code, "verification must not POST anything"


def test_a_non_enforcing_gate_is_reported_as_a_problem(src):
    """A gate that built but is not enforcing looks exactly like one that is,
    right up until it lets something through."""
    assert "NOT fully enforcing" in src
    i = src.index("NOT fully enforcing")
    # Search FORWARD from the message — "active config" also appears earlier, in
    # the comment explaining why this probe is read-only, so an absolute index
    # produced an empty slice and a vacuous pass.
    block = src[i:i + 400]
    assert "rc=1" in block


def test_a_refused_config_is_not_treated_as_a_deploy_failure(src):
    """A refusal is the gate WORKING — a fact about the config, not a fault in
    the deploy. Counting it as an error would make a correct system look broken
    every time the tunnel legitimately cannot score something."""
    i = src.index("REFUSED by the gates")
    assert "rc=1" not in src[i:i + 700]


def test_an_unreachable_gate_endpoint_is_a_problem(src):
    """An old bt-engine image has no /gates/check. Silence there would read as
    'nothing to report' when it means 'the new code is not deployed'."""
    assert "UNREACHABLE" in src


def test_verification_reports_failure_through_the_exit_code(src):
    assert 'exit "$rc"' in src
    assert "FINISHED WITH PROBLEMS" in src


def test_verify_only_mode_changes_nothing(src):
    """Being able to ask "what is actually running?" without redeploying is the
    other half of "I'm not sure what's deployed"."""
    assert "--verify" in src
    guarded = src[src.index('if [ "$VERIFY_ONLY" -eq 0 ]'):src.index("# ── 4. verification")]
    for mutating in ("Dockerfile.base", "scripts/up.sh", "scripts/deploy.sh"):
        assert mutating in guarded, f"{mutating} must sit inside the VERIFY_ONLY guard"


def test_it_never_passes_volumes(src):
    """The standing rule: --volumes deletes the trading DB and the 35M-row corpus."""
    assert "--volumes" not in src and " -v " not in src


def test_it_reports_the_corpus_version(src):
    """The factor cache keys on bt_data_version. 'Deployed' without a version
    means the cache is disabled — worth seeing, not worth guessing about."""
    assert "bt_data_version" in src


# ── the staleness fix in up.sh, which this depends on ──────────────────────

def test_up_sh_rebuilds_a_stale_base_not_just_a_missing_one():
    """The documented trap: the base's editable install caches shared/'s module
    list, so a NEW shared file is invisible until a rebuild. Checking only for a
    MISSING image never caught that, and it crash-looped bt-engine."""
    with open(UP) as f:
        up = f.read()
    assert "STALE" in up
    assert "-newermt" in up, "no mtime comparison against shared/ — staleness is unchecked"
    assert "find shared" in up
