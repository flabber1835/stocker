"""Fail-closed evidence for next-open share units."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.preopen_authority import (
    AuthorityActionOverlay,
    CURSOR_PREFIX,
    PreOpenAuthorityRefused,
    PreOpenShareUnitAuthority,
    ShareUnitCoverage,
    ShareUnitEvent,
    load_authority,
    overlay_actions,
    record_authority,
    require_recorded_authority,
    validate_for_plan,
)
from sentinel.execution.reconcile import (
    CorporateActionEvent,
    CorpusActionLookup,
)


SESSION = date(2026, 8, 21)
CUTOFF = datetime(2026, 8, 21, 13, 20, tzinfo=timezone.utc)
AS_OF = CUTOFF + timedelta(seconds=5)
EVALUATED = AS_OF + timedelta(seconds=1)


def _plan(*, plan_id: str = "sentinel-preopen-test") -> ExecutionPlan:
    return ExecutionPlan(
        plan_id=plan_id,
        decision_session=date(2026, 8, 20),
        effective_session=SESSION,
        target_exposure=Decimal(1),
        target_basket={"SEC-A": Decimal(10), "SEC-B": Decimal(20)},
        rollout_mode="PINNED_1_00", rollout_version=1)


def _split(
        *, security_id: str = "SEC-B", multiplier: str = "2",
        event_id: str = "provider-event-7",
        revision_id: str = "provider-revision-3",
        session: date = SESSION) -> ShareUnitCoverage:
    return ShareUnitCoverage.oriented(security_id, (
        ShareUnitEvent(
            event_id=event_id, revision_id=revision_id,
            effective_session=session, multiplier=Decimal(multiplier)),
    ))


def _authority(
        *, plan: ExecutionPlan | None = None,
        coverage: tuple[ShareUnitCoverage, ...] | None = None,
        effective_session: date = SESSION, complete: bool = True,
        cutoff: datetime = CUTOFF, as_of: datetime = AS_OF,
        publication_id: str = "publication-42",
        ) -> PreOpenShareUnitAuthority:
    plan = plan or _plan()
    return PreOpenShareUnitAuthority(
        plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(),
        effective_session=effective_session,
        provider="contracted-consolidated-actions",
        publication_id=publication_id, as_of=as_of, cutoff_at=cutoff,
        complete=complete,
        coverage=coverage or (
            ShareUnitCoverage.no_event("SEC-A"), _split()))


def _validate(authority, *, plan=None, required=("SEC-A", "SEC-B"),
              cutoff=CUTOFF, evaluated=EVALUATED):
    return validate_for_plan(
        authority, plan=plan or _plan(),
        required_security_ids=required,
        required_cutoff_at=cutoff, evaluated_at=evaluated)


def test_explicit_negative_and_oriented_positive_cover_every_identity():
    authority = _authority()

    multipliers = _validate(authority)

    assert multipliers == {"SEC-A": Decimal(1), "SEC-B": Decimal(2)}
    payload = authority.payload()
    assert payload["coverage"][0] == {
        "security_id": "SEC-A",
        "disposition": "NO_EVENT",
        "multiplier": "1",
        "events": [],
    }
    assert payload["coverage"][1]["events"][0]["event_id"] == \
        "provider-event-7"
    assert payload["coverage"][1]["events"][0]["revision_id"] == \
        "provider-revision-3"
    assert len(payload["authority_digest"]) == 64


def test_canonical_digest_is_independent_of_input_order_and_decimal_spelling():
    first = _authority()
    second = _authority(coverage=(
        ShareUnitCoverage(
            security_id="SEC-B", disposition="ORIENTED_EVENTS",
            multiplier=Decimal("2.00"), events=(ShareUnitEvent(
                event_id="provider-event-7", revision_id="provider-revision-3",
                effective_session=SESSION, multiplier=Decimal("2.0")),)),
        ShareUnitCoverage.no_event("SEC-A"),
    ))

    assert second == first
    assert second.digest == first.digest
    assert second.payload() == first.payload()


@pytest.mark.parametrize(
    ("coverage", "message"),
    [
        ((ShareUnitCoverage.no_event("SEC-A"),), "missing=['SEC-B']"),
        ((ShareUnitCoverage.no_event("SEC-A"), _split(),
          ShareUnitCoverage.no_event("SEC-C")), "extra=['SEC-C']"),
    ],
)
def test_identity_coverage_must_be_exact(coverage, message):
    escaped = message.replace("[", r"\[").replace("]", r"\]")
    with pytest.raises(PreOpenAuthorityRefused, match=escaped):
        _validate(_authority(coverage=coverage))


def test_empty_required_set_still_rejects_unrequested_coverage():
    with pytest.raises(PreOpenAuthorityRefused, match="extra="):
        _validate(_authority(), required=())


def test_required_identity_argument_cannot_be_one_ambiguous_string():
    with pytest.raises(PreOpenAuthorityRefused, match="iterable of strings"):
        _validate(_authority(), required="SEC-A")


def test_incomplete_publication_never_authorizes_units():
    authority = _authority(complete=False)

    with pytest.raises(PreOpenAuthorityRefused, match="incomplete"):
        _validate(authority)


def test_stale_publication_before_required_cutoff_refuses():
    old_cutoff = CUTOFF - timedelta(minutes=10)
    authority = _authority(
        cutoff=old_cutoff, as_of=old_cutoff + timedelta(seconds=1))

    with pytest.raises(PreOpenAuthorityRefused, match="stale"):
        _validate(authority)


def test_self_selected_cutoff_cannot_replace_configured_cutoff():
    authority = _authority(cutoff=CUTOFF - timedelta(minutes=1))

    with pytest.raises(PreOpenAuthorityRefused, match="different provider cutoff"):
        _validate(authority)


def test_future_provider_publication_refuses():
    with pytest.raises(PreOpenAuthorityRefused, match="future"):
        _validate(_authority(), evaluated=AS_OF - timedelta(microseconds=1))


def test_wrong_plan_id_fingerprint_or_effective_session_refuses():
    authority = _authority()
    another_id = _plan(plan_id="sentinel-another-plan")
    with pytest.raises(PreOpenAuthorityRefused, match="another plan"):
        _validate(authority, plan=another_id)

    changed = replace(
        _plan(), target_basket={"SEC-A": Decimal(11), "SEC-B": Decimal(20)})
    with pytest.raises(PreOpenAuthorityRefused, match="plan economics"):
        _validate(authority, plan=changed)

    wrong_session = _authority(
        coverage=(ShareUnitCoverage.no_event("SEC-A"),
                  ShareUnitCoverage.no_event("SEC-B")),
        effective_session=date(2026, 8, 24))
    with pytest.raises(PreOpenAuthorityRefused, match="wrong effective session"):
        _validate(wrong_session)


def test_no_event_is_not_an_implicit_default():
    with pytest.raises(PreOpenAuthorityRefused, match="NO_EVENT"):
        ShareUnitCoverage(
            security_id="SEC-A", disposition="NO_EVENT",
            multiplier=Decimal(2), events=())


def test_positive_multiplier_requires_event_and_revision_identity():
    with pytest.raises(PreOpenAuthorityRefused, match="durable event"):
        ShareUnitCoverage(
            security_id="SEC-A", disposition="ORIENTED_EVENTS",
            multiplier=Decimal(2), events=())
    with pytest.raises(PreOpenAuthorityRefused, match="event revision id"):
        ShareUnitEvent(
            event_id="event", revision_id="", effective_session=SESSION,
            multiplier=Decimal(2))


def test_optional_exact_rational_terms_are_all_or_none_positive_and_consistent():
    with pytest.raises(PreOpenAuthorityRefused, match="both numerator"):
        ShareUnitEvent(
            event_id="event", revision_id="revision",
            effective_session=SESSION,
            multiplier=Decimal("0.03333333333333333"),
            canonical_numerator=1)
    with pytest.raises(PreOpenAuthorityRefused, match="positive integers"):
        ShareUnitEvent(
            event_id="event", revision_id="revision",
            effective_session=SESSION, multiplier=Decimal("0.5"),
            canonical_numerator=0, canonical_denominator=2)
    with pytest.raises(PreOpenAuthorityRefused, match="contradicts"):
        ShareUnitEvent(
            event_id="event", revision_id="revision",
            effective_session=SESSION, multiplier=Decimal("0.5"),
            canonical_numerator=1, canonical_denominator=3)

    event = ShareUnitEvent(
        event_id="event", revision_id="revision",
        effective_session=SESSION,
        multiplier=Decimal("0.03333333333333333"),
        canonical_numerator=1, canonical_denominator=30)
    assert event.payload()["canonical_numerator"] == 1
    assert event.payload()["canonical_denominator"] == 30


def test_aggregate_multiplier_must_equal_oriented_event_product():
    with pytest.raises(PreOpenAuthorityRefused, match="event product"):
        ShareUnitCoverage(
            security_id="SEC-A", disposition="ORIENTED_EVENTS",
            multiplier=Decimal(3), events=(ShareUnitEvent(
                event_id="event", revision_id="revision",
                effective_session=SESSION, multiplier=Decimal(2)),))


def test_one_publication_cannot_carry_two_revisions_of_the_same_event():
    events = (
        ShareUnitEvent(
            event_id="event", revision_id="revision-1",
            effective_session=SESSION, multiplier=Decimal(2)),
        ShareUnitEvent(
            event_id="event", revision_id="revision-2",
            effective_session=SESSION, multiplier=Decimal("0.5")),
    )

    with pytest.raises(PreOpenAuthorityRefused, match="repeat or revise"):
        ShareUnitCoverage.oriented("SEC-A", events)


def test_event_effective_session_must_match_publication_session():
    wrong = _split(session=date(2026, 8, 20))
    with pytest.raises(PreOpenAuthorityRefused, match="wrong effective session"):
        _authority(coverage=(ShareUnitCoverage.no_event("SEC-A"), wrong))


def _corpus_event(*, multiplier=Decimal(2), reason="published scalar"):
    return CorporateActionEvent(
        security_id="SEC-B", ticker="BBB", session=SESSION,
        action="split", value=multiplier, contraticker=None,
        source_row_id="corpus-split", reason=reason,
        canonical_multiplier=multiplier)


def test_authority_overlay_replaces_matching_open_event_without_double_apply():
    base = CorpusActionLookup(
        start=date(2026, 8, 18),
        events={"SEC-B": (
            (date(2026, 8, 19), Decimal(3)),
            (SESSION, Decimal(2)),)},
        scalar_events=(_corpus_event(),))
    authority = _authority(coverage=(_split(),))

    overlaid = overlay_actions(base, authority)

    assert isinstance(overlaid, AuthorityActionOverlay)
    assert overlaid("SEC-B") == Decimal(6)
    assert overlaid("SEC-B", date(2026, 8, 19)) == Decimal(2)
    assert len(overlaid.scalar_evidence_for(("SEC-B",))) == 1
    assert overlaid.scalar_evidence_for(("SEC-B",))[0].source_row_id \
        .startswith("preopen-share-unit-authority/v1:")


def test_authority_overlay_refuses_corpus_contradictions():
    positive_base = CorpusActionLookup(
        start=date(2026, 8, 20),
        events={"SEC-B": ((SESSION, Decimal(2)),)},
        scalar_events=(_corpus_event(),))
    with pytest.raises(PreOpenAuthorityRefused, match="contradicts corpus"):
        overlay_actions(
            positive_base, _authority(coverage=(
                ShareUnitCoverage.oriented("SEC-B", (ShareUnitEvent(
                    event_id="different", revision_id="revision",
                    effective_session=SESSION, multiplier=Decimal(3)),)),)))
    with pytest.raises(PreOpenAuthorityRefused, match="negative pre-open"):
        overlay_actions(
            positive_base, _authority(coverage=(
                ShareUnitCoverage.no_event("SEC-B"),)))


def test_provider_event_resolves_only_same_identity_scalar_uncertainty():
    identified = _corpus_event(reason="published bar absent")
    ticker_only = CorporateActionEvent(
        security_id=None, ticker="BBB", session=SESSION,
        action="split", value=Decimal(2), contraticker=None,
        source_row_id="ticker-only", reason="permanent identity absent")
    base = CorpusActionLookup(
        start=date(2026, 8, 20), events={},
        unresolved_events=(identified, ticker_only))

    overlaid = overlay_actions(base, _authority(coverage=(_split(),)))

    material = overlaid.material_events_for(
        security_ids=("SEC-B",), symbols=("BBB",))
    assert material == (ticker_only,)


def test_overlay_emits_exact_reverse_ratio_for_target_reprojection():
    event = ShareUnitEvent(
        event_id="reverse-30", revision_id="revision-9",
        effective_session=SESSION,
        multiplier=Decimal("0.03333333333333333"),
        canonical_numerator=1, canonical_denominator=30)
    authority = _authority(coverage=(
        ShareUnitCoverage.oriented("SEC-B", (event,)),))
    base = CorpusActionLookup(start=date(2026, 8, 20), events={})

    evidence = overlay_actions(
        base, authority).scalar_evidence_for(("SEC-B",))[0].to_dict()

    assert evidence["canonical_multiplier"] == "0.03333333333333333"
    assert evidence["canonical_numerator"] == 1
    assert evidence["canonical_denominator"] == 30


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params):
        normalized = " ".join(str(query).split()).lower()
        if normalized.startswith(
                "select session,state from sentinel_processed_sessions"):
            self.result = self.conn.rows.get(params[0])
            return
        if normalized.startswith("insert into sentinel_processed_sessions"):
            name, session, state = params
            self.conn.rows.setdefault(
                name, (date.fromisoformat(str(session)), json.loads(state)))
            self.result = None
            return
        raise AssertionError(query)

    def fetchone(self):
        return self.result


class _Connection:
    def __init__(self):
        self.rows = {}
        self.commits = 0

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1


def test_record_is_immutable_and_idempotent():
    conn = _Connection()
    authority = _authority()

    assert record_authority(conn, authority) == authority
    assert record_authority(conn, authority) == authority
    assert conn.commits == 1
    assert load_authority(conn, plan_id=authority.plan_id) == authority
    assert f"{CURSOR_PREFIX}{authority.plan_id}" in conn.rows

    changed = _authority(publication_id="publication-43")
    with pytest.raises(PreOpenAuthorityRefused, match="immutable"):
        record_authority(conn, changed)


def test_incomplete_publication_cannot_be_persisted_as_authority():
    with pytest.raises(PreOpenAuthorityRefused, match="incomplete"):
        record_authority(_Connection(), _authority(complete=False))


def test_durable_content_tamper_is_detected_by_digest():
    conn = _Connection()
    authority = record_authority(conn, _authority())
    name = f"{CURSOR_PREFIX}{authority.plan_id}"
    session, state = conn.rows[name]
    state["coverage"][0]["security_id"] = "SEC-TAMPERED"
    conn.rows[name] = (session, state)

    with pytest.raises(PreOpenAuthorityRefused, match="digest"):
        load_authority(conn, plan_id=authority.plan_id)


def test_durable_row_session_tamper_is_detected():
    conn = _Connection()
    authority = record_authority(conn, _authority())
    name = f"{CURSOR_PREFIX}{authority.plan_id}"
    _session, state = conn.rows[name]
    conn.rows[name] = (date(2026, 8, 22), state)

    with pytest.raises(PreOpenAuthorityRefused, match="durable row"):
        load_authority(conn, plan_id=authority.plan_id)


def test_absent_record_never_becomes_implicit_no_event_authority():
    conn = _Connection()

    with pytest.raises(PreOpenAuthorityRefused, match="is absent"):
        require_recorded_authority(
            conn, plan=_plan(), required_security_ids=("SEC-A", "SEC-B"),
            required_cutoff_at=CUTOFF, evaluated_at=EVALUATED)


def test_recorded_authority_revalidates_plan_and_exact_coverage():
    conn = _Connection()
    authority = record_authority(conn, _authority())

    stored, multipliers = require_recorded_authority(
        conn, plan=_plan(), required_security_ids=("SEC-B", "SEC-A"),
        required_cutoff_at=CUTOFF, evaluated_at=EVALUATED)

    assert stored == authority
    assert multipliers == {"SEC-A": Decimal(1), "SEC-B": Decimal(2)}
