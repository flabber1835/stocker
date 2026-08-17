from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if not (ROOT / "sentinel").is_dir():
    ROOT = ROOT / "repo"


def test_operational_readiness_defaults_to_a_real_instant_not_midnight():
    source = (ROOT / "sentinel" / "feed" / "readiness.py").read_text(
        encoding="utf-8")

    # No-argument check-data is an operational question: is this corpus ready
    # now? A date-only default is interpreted as exchange-local midnight and can
    # therefore pass Friday's frontier after Monday has already closed.
    assert "today = today or _dt.date.today().isoformat()" not in source
    assert (
        "today = today or _dt.datetime.now(_dt.timezone.utc).isoformat()"
        in source
    )

    # Explicit --today remains a caller-supplied historical observation point;
    # only the omitted/default case is replaced by the wall-clock instant.
    assert "fresh = _cal.freshness(frontier, now_et=today)" in source
