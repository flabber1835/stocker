from pathlib import Path


def test_chronological_replay_resolves_main_once_and_propagates_identity() -> None:
    workflow = Path(
        ".github/workflows/backtester-ldrc-nonpit-vs-pit-certified.yml"
    ).read_text(encoding="utf-8")
    launcher = Path("backtester/run_ldrc_current_main.py").read_text(encoding="utf-8")

    # The workflow must not carry the obsolete pre-kernel Production pin that
    # caused ModuleNotFoundError after the replay code migrated to core.kernel.
    assert "887f479b15ad861313da666ad698034d3847121c" not in workflow
    assert "ref: main" in workflow
    assert "BACKTESTER_MAIN_SHA=${ACTUAL}" in workflow
    assert "test -f main-src/sentinel/core/kernel.py" in workflow
    assert "python backtester/run_ldrc_current_main.py" in workflow

    # The exact SHA resolved by checkout is the only Production identity the
    # retained wrappers may advertise or validate during the run.
    assert 'os.environ.get("BACKTESTER_MAIN_SHA"' in launcher
    assert "corrected.prod.EXPECTED_MAIN_SHA = sha" in launcher
    assert "corrected.runner.EXPECTED_MAIN_SHA = sha" in launcher
    assert "Production module escaped exact run-start checkout" in launcher


def test_triggering_backtester_revision_is_immutable() -> None:
    workflow = Path(
        ".github/workflows/backtester-ldrc-nonpit-vs-pit-certified.yml"
    ).read_text(encoding="utf-8")
    assert "ref: ${{ github.sha }}" in workflow
    assert 'test "$(git rev-parse HEAD)" = "${GITHUB_SHA}"' in workflow
