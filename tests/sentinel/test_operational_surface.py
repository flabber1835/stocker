import os
import re
import subprocess
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
    for name in ("docker-compose.sentinel.yml",):
        lines = _read(name).splitlines()
        published = [line.strip() for line in lines
                     if line.strip().startswith('- "') and ":" in line]
        assert published
        assert all(line.startswith('- "127.0.0.1:') for line in published)


def test_all_active_python_images_require_artifact_hashes():
    for name in ("Dockerfile.sentinel", "Dockerfile.sentinel-test"):
        text = _read(name)
        assert "--require-hashes" in text, name
        assert "PIP_TRUSTED_HOST" not in text, name
    assert "--no-build-isolation" in _read("Dockerfile.sentinel")


def test_shell_entrypoints_are_forced_to_lf_in_every_checkout():
    attributes = _read(".gitattributes").splitlines()
    assert "*.sh text eol=lf" in attributes


def test_pull_requests_run_the_complete_sentinel_safety_suite():
    workflow = _read(".github/workflows/sentinel-safety.yml")
    assert "pull_request:" in workflow
    branches = re.search(r"branches:\s*\[([^]]+)\]", workflow)
    assert branches and "main" in {
        branch.strip() for branch in branches.group(1).split(",")}
    assert "permissions:\n  contents: read" in workflow
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" \
        in workflow
    assert "-f Dockerfile.sentinel -t sentinel:latest ." in workflow
    assert "Dockerfile.sentinel-authorized" in workflow
    assert "sentinel-authorized:ci" in workflow
    assert "-f Dockerfile.sentinel-test -t sentinel-test:ci" in workflow
    assert "SENTINEL_IMAGE=sentinel-authorized:ci" in workflow
    assert workflow.count('--build-arg SOURCE_GIT_SHA="${TESTED_SHA}"') == 3
    assert 'TESTED_SHA="$(git rev-parse HEAD)"' in workflow
    assert "tests/sentinel -q -ra" in workflow
    assert "tee /tmp/sentinel-complete.txt" in workflow
    assert "the complete Sentinel run skipped tests" in workflow
    assert "--network none" in workflow
    assert "docker-compose.sentinel-backup.yml" in workflow
    assert "fetch-depth: 2" in workflow
    assert "git diff --check HEAD^1 HEAD" in workflow


def test_pull_request_safety_is_read_only_and_publication_is_main_only():
    safety = _read(".github/workflows/sentinel-safety.yml")
    publication = _read(".github/workflows/sentinel-publish.yml")
    codeowners = _read(".github/CODEOWNERS")

    permissions = safety.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in permissions
    assert "packages: write" not in permissions
    assert "id-token: write" not in permissions
    assert "docker push" not in safety
    assert "ACTIONS_ID_TOKEN_REQUEST" not in safety

    assert "workflow_run:" in publication
    assert "branches: [main]" in publication
    assert "workflow_run.event == 'push'" in publication
    assert "workflow_run.head_branch == 'main'" in publication
    assert "workflow_run.workflow_id == 333697638" in publication
    assert ("workflow_run.path == "
            "'.github/workflows/sentinel-safety.yml'") in publication
    assert "workflow_run.repository.id == 1233957439" in publication
    assert "workflow_run.head_repository.id == 1233957439" in publication
    assert "packages: write" in publication
    assert "id-token: write" in publication
    assert "attestations: write" in publication
    assert "run-id: ${{ github.event.workflow_run.id }}" in publication
    assert "/.github/workflows/ @flabber1835" in codeowners


def test_pull_request_ci_proves_it_is_testing_the_synthetic_merge():
    workflow = _read(".github/workflows/sentinel-safety.yml")
    assert "pull_request:\n    branches: [main]" in workflow
    assert "merge_group:" in workflow
    assert 'scope: ${{ fromJSON(github.event_name == \'pull_request\'' in workflow
    assert 'if [ \'${{ matrix.scope }}\' = \'exact-head\' ]' in workflow
    assert 'test "$TESTED_SHA" = "$expected_head"' in workflow
    assert 'test "$TESTED_SHA" = "$GITHUB_SHA"' in workflow
    assert 'echo "TESTED_SHA=$TESTED_SHA" >> "$GITHUB_ENV"' in workflow
    assert "printf -- '- commit: `%s`\\n' \"$TESTED_SHA\"" in workflow
    for variable in ("tree_hash", "GITHUB_RUN_ID", "dependency_lock_hash",
                     "runtime_digest", "test_manifest_hash"):
        assert f'"${variable}"' in workflow
    assert 'printf \'%s\\n\' "$TESTED_SHA"' in workflow
    assert "git rev-list --parents -n 1 HEAD" in workflow
    assert 'if [ "$parent_count" -ne 2 ]' in workflow
    assert "pull-request checkout is not a synthetic merge commit" in workflow
    assert "git merge-base --is-ancestor HEAD^1 HEAD" in workflow
    assert "git merge-base --is-ancestor HEAD^2 HEAD" in workflow
    assert "name: sentinel-${{ matrix.scope }}" in workflow
    assert "name: host-python-38-${{ matrix.scope }}" in workflow


def test_main_push_runs_exact_sha_safety_and_branch_coverage():
    workflow = _read(".github/workflows/sentinel-safety.yml")
    assert "push:\n    branches:\n      - main" in workflow
    assert "- 'codex/**'" in workflow
    assert "coverage run --branch" in workflow
    assert "tests/sentinel/test_pr293_automation_fixes.py" in workflow
    assert "coverage report --precision=2 --fail-under=80.00" in workflow
    for evidence in (
            "source tree", "workflow run", "dependency locks",
            "authorized image", "test manifest", "schema epoch",
            "semantic epoch"):
        assert evidence in workflow


def test_publication_persists_verifiable_provenance_before_authorized_tag():
    safety = _read(".github/workflows/sentinel-safety.yml")
    publication = _read(".github/workflows/sentinel-publish.yml")

    assert "sha256sum sentinel-authorized.tar COMMIT > SHA256SUMS" in safety
    assert "sha256sum /tmp/sentinel-tested-image" not in safety
    assert "actions/attest-build-provenance@e8998f949152b193b063cb0ec769d69d929409be" \
        in publication
    assert "push-to-registry: false" in publication
    assert ("registry@sha256:"
            "a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373") \
        in publication
    assert "--publish 127.0.0.1:5000:5000" in publication
    assert 'docker push "$local_tag"' in publication
    assert publication.count("docker push ") == 1
    assert ("oras-project/setup-oras@"
            "1d808f7d7f6995cc68b7bf507bfe5c5446e1dc9d") in publication
    assert "version: 1.3.3" in publication
    assert "oras cp --from-plain-http" in publication
    assert publication.count("oras cp ") == 1
    assert '"${LOCAL_REPOSITORY}@${SUBJECT_DIGEST}"' in publication
    assert 'final_digest="$(oras resolve "$FINAL_REF")"' in publication
    assert 'test "$final_digest" = "$SUBJECT_DIGEST"' in publication
    assert "attestation.sigstore.json" in publication
    assert "base64.b64decode" in publication
    assert 'statement.get("subject") != expected_subject' in publication
    assert "https://in-toto.io/Statement/v1" in publication
    assert "https://slsa.dev/provenance/v1" in publication
    assert "retention-days: 90" in publication
    assert "sha256sum provenance.json attestation.sigstore.json > SHA256SUMS" \
        in publication
    assert "sha256sum /tmp/sentinel-provenance" not in publication
    assert "ACTIONS_ID_TOKEN_REQUEST" not in publication

    local = publication.index('docker push "$local_tag"')
    attested = publication.index("uses: actions/attest-build-provenance@")
    retained = publication.index("name: Retain signed promotion evidence")
    login = publication.index("oras login ghcr.io")
    final = publication.index("oras cp --from-plain-http")
    assert local < attested < retained < login < final
    pre_attestation = publication[:attested]
    assert "oras login ghcr.io" not in pre_attestation
    assert "oras cp " not in pre_attestation
    assert "docker login ghcr.io" not in pre_attestation
    assert "docker buildx imagetools create" not in pre_attestation


def test_required_workflow_activation_is_exact_and_fail_closed():
    contract = _read("docs/f92c0cc-safety-reconstruction.md")
    assert '"type": "workflows"' in contract
    assert '"repository_ids": [1233957439]' in contract
    assert '"path": ".github/workflows/sentinel-safety.yml"' in contract
    assert '"repository_id": 1233957439' in contract
    assert '"ref": "refs/heads/main"' in contract
    assert "POST /orgs/{org}/rulesets" in contract
    assert "ruleset `21878525`" in contract


def test_ci_compiles_python_and_syntax_checks_every_tracked_shell_script():
    workflow = _read(".github/workflows/sentinel-safety.yml")
    assert workflow.count("-m compileall -q -f") == 2
    assert "python -m compileall -q -f scripts" in workflow
    for path in ("/app/sentinel", "/usr/local/lib/python3.12/site-packages/stock_strategy_shared",
                 "/work/tests/sentinel", "/work/tests/scripts", "/work/tools",
                 "/work/repo/scripts"):
        assert path in workflow
    assert "mapfile -d '' shell_scripts < <(git ls-files -z -- '*.sh')" \
        in workflow
    assert 'if [ "${#shell_scripts[@]}" -eq 0 ]' in workflow
    assert 'bash -n "${shell_scripts[@]}"' in workflow


def test_ci_pytest_logs_are_pipefail_safe_and_distinguish_skip_from_xfail():
    workflow = _read(".github/workflows/sentinel-safety.yml")
    protected_logs = (
        "/tmp/sentinel-complete.txt",
        "/tmp/sentinel-scripts.txt",
        "/tmp/wealth-core-prospective.txt",
    )
    assert workflow.count("set -euo pipefail") >= 4
    assert workflow.count("-q -ra 2>&1 | tee") == len(protected_logs)
    for log in protected_logs:
        assert f"-q -ra 2>&1 | tee {log}" in workflow
    assert workflow.count("[0-9]+ skipped") == 1

    # The gate is intentionally specific to ordinary skips. Strict xfails are
    # reported by pytest's -ra summary and remain visible certification debt;
    # the word "xfailed" must not be misclassified as an ordinary skip.
    skip_summary = re.compile(r"(^|, )[0-9]+ skipped(,| in |$)")
    assert skip_summary.search("1865 passed, 1 skipped in 10.0s")
    assert skip_summary.search("1 skipped in 1.0s")
    assert not skip_summary.search("434 passed, 3 xfailed in 10.0s")


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


def test_make_certify_is_a_fail_closed_external_boundary():
    body = _read("Makefile")
    target = body[body.index("certify:"):]
    assert "bash scripts/sentinel-certify.sh" in target
    assert "--build-only" not in target
    assert "--verify-only" not in target


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
