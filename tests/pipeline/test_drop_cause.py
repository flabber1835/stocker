"""enrich_drop_cause — orphan-exit reasons must say WHY the builder dropped a
held name (the MU finding: a rank-6 exit whose falling-knife cause took two
manual SQL queries to discover)."""
from app.main import enrich_drop_cause

ORPHAN = ("Held at broker, dropped from target for 2 consecutive builds "
          "(rank=6) — exiting (target is binding)")


def test_vetter_cause_appended_to_orphan_exit():
    out = enrich_drop_cause("exit", ORPHAN,
                            "drawdown: FALLING-KNIFE VETO: excess -24.5% (limit -20%)")
    assert out.startswith(ORPHAN)
    assert "| drop cause: vetter drawdown: FALLING-KNIFE VETO" in out


def test_at_risk_countdown_gets_cause_too():
    out = enrich_drop_cause("at_risk", ORPHAN.replace("exiting", "at risk"), None)
    assert out.endswith("| drop cause: not selected by builder (score/caps)")


def test_non_orphan_reasons_untouched():
    r = "Held and in target (rank=2), overweight: drift=+4.58%"
    assert enrich_drop_cause("sell_trim", r, "drawdown: veto") == r
    assert enrich_drop_cause("entry", "New entry (rank=5)", None) == "New entry (rank=5)"
    assert enrich_drop_cause("exit", None, None) == ""


def test_exit_without_target_drop_phrase_untouched():
    r = "cold-start exit: rank beyond exit_rank for 3 days"
    assert enrich_drop_cause("exit", r, "drawdown: veto") == r
