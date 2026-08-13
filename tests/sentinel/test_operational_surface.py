import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SUITE = Path(__file__).resolve().parents[2]


def _read(name: str) -> str:
    return (ROOT / name).read_text()


def test_public_readme_describes_only_the_current_architecture():
    text = _read("README.md")
    assert text.startswith("# Sentinel")
    assert "Stocker is retired" in text
    for retired in ("redis", "db-migrator", "trade-executor", "LLM-generated"):
        assert retired not in text


def test_env_example_has_no_live_trading_or_retired_service_controls():
    text = _read(".env.example")
    assert "paper-api.alpaca.markets" in text
    assert "LIVE_TRADING_ENABLED" not in text
    assert "PAPER_ONLY" not in text
    assert "IBKR_" not in text
    assert "AV_API_KEY" not in text
    assert "SENTINEL_POSTGRES_PASSWORD=" in text
    assert "BT_POSTGRES_PASSWORD=" in text


def test_retired_operational_scripts_are_fail_closed_tombstones():
    for name in ("scripts/deploy-wealth-core.sh", "scripts/retire-stocker.sh"):
        text = _read(name)
        assert "REFUSED:" in text
        assert "exit 64" in text
        assert "docker compose down" not in text
        assert "git pull" not in text


def test_make_image_never_emits_an_unknown_or_dirty_source_tag():
    text = _read("Makefile")
    assert "|| echo unknown" not in text
    assert "source has no Git commit identity" in text
    assert "source tree is dirty" in text
    assert "--build-arg SOURCE_GIT_SHA=" in text


def test_every_published_operational_port_is_loopback_only():
    for name in ("docker-compose.sentinel.yml", "docker-compose.backtest.yml"):
        lines = _read(name).splitlines()
        published = [line.strip() for line in lines
                     if line.strip().startswith('- "') and ":" in line]
        assert published
        assert all(line.startswith('- "127.0.0.1:') for line in published)


def test_bt_engine_startup_and_health_fail_closed():
    text = _read("services/bt-engine/app/main.py")
    lifespan = text[text.index("async def lifespan"):text.index("app = FastAPI")]
    assert "except" not in lifespan
    assert "_ready = True" in lifespan
    health = text[text.index('app.get("/health")'):]
    assert "HTTPException(503" in health
    assert "bt_wealth_core_runs" in health
    assert "load_ready_data_generation(conn)" in health
    assert '"data_generation": generation.to_dict()' in health


def test_all_active_python_images_require_artifact_hashes():
    for name in ("Dockerfile.sentinel", "Dockerfile.base",
                 "services/bt-engine/Dockerfile",
                 "services/bt-data/Dockerfile"):
        text = _read(name)
        assert "--require-hashes" in text, name
        assert "PIP_TRUSTED_HOST" not in text, name
    assert (ROOT / "services/bt-engine/requirements.lock").exists()
    assert (ROOT / "services/bt-data/requirements.lock").exists()
    for name in ("Dockerfile.sentinel", "Dockerfile.base"):
        text = _read(name)
        assert "--no-build-isolation" in text


def test_expected_golden_drift_is_exact_strict_xfail_not_a_suite_mask():
    runner = _read("scripts/run-tests.sh")
    assert "KNOWN_RED" not in runner
    assert "strict xfail" in runner
    fixture = (SUITE / "tests/wealth_core/test_golden_fixture.py").read_text()
    performance = (SUITE / "tests/wealth_core/test_performance_integration.py").read_text()
    assert fixture.count("strict=True") == 2
    assert performance.count("strict=True") == 1


def _executable(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(0o755)
    return path


def test_make_certify_requires_and_forwards_an_exact_window():
    body = _read("Makefile")
    target = body[body.index("certify:"):]
    assert 'test -n "$(START)" -a -n "$(END)"' in target
    assert 'sentinel-certify.sh --start "$(START)" --end "$(END)"' in target


def test_make_host_test_runner_installs_async_pytest_support():
    body = _read("Makefile")
    test_recipe = body.split("test:", 1)[1].split("\n\n", 1)[0]
    assert "pytest-asyncio" in test_recipe


def test_test_runner_refuses_pytest_nothing_collected(tmp_path):
    root = tmp_path / "repository"
    scripts = root / "scripts"
    suite = root / "tests" / "sentinel"
    scripts.mkdir(parents=True)
    suite.mkdir(parents=True)
    runner = _executable(
        scripts / "run-tests.sh", _read("scripts/run-tests.sh"))
    (suite / "test_placeholder.py").write_text("def test_placeholder(): pass\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _executable(fake_bin / "python", "#!/bin/sh\nexit 5\n")
    env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}

    result = subprocess.run(
        ["bash", str(runner), "-q"], cwd=root, env=env,
        capture_output=True, text=True, timeout=30)

    assert result.returncode != 0
    assert "pytest collected no tests" in result.stdout


def test_test_runner_refuses_when_global_discovery_finds_no_suites(tmp_path):
    root = tmp_path / "empty-repository"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (root / "tests").mkdir()
    runner = scripts / "run-tests.sh"
    runner.write_text(_read("scripts/run-tests.sh"))
    runner.chmod(0o755)

    result = subprocess.run(
        ["bash", str(runner)], cwd=root,
        capture_output=True, text=True, timeout=30)

    assert result.returncode != 0
    assert "test discovery found no suites" in result.stderr


def test_test_runner_skips_helper_only_directory_but_refuses_real_empty_suite(
        tmp_path):
    root = tmp_path / "repository"
    scripts = root / "scripts"
    support = root / "tests" / "support"
    real = root / "tests" / "real"
    fake_bin = root / "bin"
    for path in (scripts, support, real, fake_bin):
        path.mkdir(parents=True, exist_ok=True)
    runner = scripts / "run-tests.sh"
    runner.write_text(_read("scripts/run-tests.sh"))
    runner.chmod(0o755)
    (support / "helpers.py").write_text("HELPER = True\n")
    (real / "test_empty.py").write_text(
        "# A discoverable suite whose pytest process reports no collection.\n")
    calls = root / "python-calls.log"
    _executable(fake_bin / "python", """#!/bin/sh
printf '%s\n' "$*" >> "$PYTHON_CALLS"
exit 5
""")
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "PYTHON_CALLS": str(calls),
    }

    result = subprocess.run(
        ["bash", str(runner), "-q"], cwd=root, env=env,
        capture_output=True, text=True, timeout=30)

    invoked = calls.read_text()
    assert result.returncode != 0
    assert "tests/real" in invoked
    assert "tests/support" not in invoked
    assert "pytest collected no tests for tests/real" in result.stdout


def _run_launcher(tmp_path: Path, manifest_payload: str):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "docker.log"
    _executable(fake_bin / "docker", """#!/bin/sh
printf '%s\n' "$*" >> "$DOCKER_LOG"
if [ "$1" = image ] && [ "$2" = inspect ]; then
  printf '%s\n' 'sha256:test-engine'
fi
exit 0
""")
    _executable(fake_bin / "python3", f"""#!/bin/sh
if [ "$1" = scripts/compose_image.py ]; then
  printf '%s\n' fake-bt-engine
  exit 0
fi
exec {shlex.quote(sys.executable)} "$@"
""")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(manifest_payload)
    env = {
        **os.environ,
        "DOCKER_LOG": str(log),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    }
    result = subprocess.run(
        ["bash", "scripts/bt-engine-up.sh", "--no-build", "--manifest",
         str(manifest)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    return result, log.read_text() if log.exists() else ""


def test_bt_engine_launcher_refuses_malformed_or_identityless_manifest(
        tmp_path):
    payloads = (
        "not-json",
        json.dumps({}),
        json.dumps({"bt_engine_image": {"id": ""}}),
    )
    for number, payload in enumerate(payloads):
        case = tmp_path / str(number)
        case.mkdir()
        result, docker_calls = _run_launcher(case, payload)
        assert result.returncode != 0
        assert "REFUSED:" in result.stderr
        assert " up -d " not in f" {docker_calls} "


def test_bt_engine_launcher_starts_only_the_manifest_image(tmp_path):
    result, docker_calls = _run_launcher(
        tmp_path, json.dumps({
            "bt_engine_image": {"id": "sha256:test-engine"}}))
    assert result.returncode == 0, result.stderr
    assert "compose -f docker-compose.backtest.yml up -d --force-recreate " \
        "bt-engine" in docker_calls
