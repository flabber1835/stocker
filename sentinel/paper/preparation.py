"""Paper state warm/replay, immutable plan adoption, and plan status."""

from __future__ import annotations

import math

from datetime import date, datetime, timedelta

from decimal import Decimal, InvalidOperation

from typing import Mapping, Optional

from zoneinfo import ZoneInfo

from sentinel import (
    binding as binding_mod,
    dual_plan_authority,
    identity as system_identity,
    informational_paper_mirror,
    schema,
    trial,
    trial_close,
    trial_fills,
)

from sentinel.authority import (
    AuthorityRefused,
    PAPER_OBSERVATION_ONLY,
    RolloutMode,
    load_rollout_state,
    require_observation_safety_authority,
)

from sentinel.config import DEFAULT_BASE_URL, assert_paper_url

from sentinel.controller.concordance import is_concordance_identity

from sentinel.controller.concordance_parent import load as load_concordance_parent

from sentinel.controller.frozen_rule import ControllerConfig, load as load_controller

from sentinel.controller.ldrc import (
    LDRCConfig, STRATEGY_ID as LDRC_STRATEGY_ID,
    STRATEGY_VERSION as LDRC_STRATEGY_VERSION,
)

from sentinel.controller.machine import Controller

from sentinel.core import catchup

from sentinel.core.decision import (
    DEFENSIVE_SECURITY_ID,
    build_execution_plan,
    publication_fingerprint,
    runtime_strategy_identity,
    shadow_target,
)

from sentinel.core.loader import (
    CausalMetadataUnavailable,
    load_causal_meta_history, load_meta, load_window)

from sentinel.core.production import (
    CONCORDANCE_WITNESS_PROSPECTIVE,
    SessionState,
    advance_and_persist,
    load_published_session,
    warm_session_state,
)

from sentinel.execution import broker_cash, executor, journal

from sentinel.execution import preopen_authority

from sentinel.execution import reconcile as reconciliation

from sentinel.execution.authority_gate import (
    build_fresh_execution_guard,
    require_current_authority,
)

from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    BrokerInstrument,
    BrokerObservation,
    ExecutionBroker,
    MalformedBrokerEvidence,
)

from sentinel.execution.guarded import (
    AutomationExecutionGrant,
    BrokerAuthorityRefused,
    BrokerOperation,
    GuardedExecutionBroker,
    ManualExecutionGrant,
    PaperPreparationGrant,
)

from sentinel.feed import calendar, publication, readiness, store as feed_store

from .model import (
    PaperActivationRefused,
    PaperRetryableRefused,
    PreOpenShareUnitAuthorityUnavailable,
    PreparationResult,
)

from .inspection import (
    DEFENSIVE_SYMBOL,
    _require_certified_paper_broker,
    _account_or_refuse,
)

from .validation import (
    _assert_concordance_witness_authority,
    _hash,
    _readiness_or_refuse,
    _missed_sessions,
    _assert_deterministic_plan_id,
    _guard_broker,
    _state_and_plan_or_refuse,
    _assert_plan_authorities,
)

from .cash import (
    _broker_cash_state_or_refuse,
    _cash_authority_or_refuse,
)

from .targets import (
    _action_lookup,
    _target_action_lookup,
    _preopen_active_security_ids,
    _preopen_views_or_none,
    _revalidate_preopen_authority_or_refuse,
    _official_preopen_cutoff,
)

from .reconciliation_evidence import _clean_or_refuse

from .finalization import _finalize_due_succeeded_cycle_or_refuse

SIMPLIFIED_LDRC_STRATEGY_ID = "sentinel-concordance-simplified-ldrc"

SIMPLIFIED_LDRC_STRATEGY_VERSION = 3

def _default_paper_strategy() -> tuple[ControllerConfig, dict[str, str]]:
    """Return the one paper-trial strategy: hardened parent + simplified LD-RC.

    The assertions are intentionally redundant with source identity. They make
    an accidental rollback to the older five-condition/legacy recovery model a
    startup refusal instead of a plausible but different trading strategy.
    """
    if (LDRC_STRATEGY_ID != SIMPLIFIED_LDRC_STRATEGY_ID
            or LDRC_STRATEGY_VERSION != SIMPLIFIED_LDRC_STRATEGY_VERSION):
        raise PaperActivationRefused(
            "paper runtime requires Simplified Concordance LD-RC v3")
    cfg = LDRCConfig()
    expected = (0.55, -0.10, -0.08, 0.00, 7, 0.11)
    actual = (
        cfg.divergence_ceiling, cfg.wc_drawdown_trigger,
        cfg.recent_r20_trigger, cfg.spy_r20_floor,
        cfg.recovery_sessions, cfg.spy_v_rebound,
    )
    if actual != expected:
        raise PaperActivationRefused(
            "Simplified LD-RC v3 constants differ from the retained strategy")
    controller = load_concordance_parent()
    identity = runtime_strategy_identity(controller, concordance=True)
    if (identity.get("allocation_overlay") != SIMPLIFIED_LDRC_STRATEGY_ID
            or identity.get("allocation_overlay_version")
            != str(SIMPLIFIED_LDRC_STRATEGY_VERSION)):
        raise PaperActivationRefused(
            "paper strategy identity does not name Simplified LD-RC v3")
    return controller, identity

def _load_marks_and_tickers(conn, state: SessionState, session: str
                            ) -> tuple[dict, dict]:
    target = shadow_target(state)
    security_ids = sorted(target.shares)
    tickers = dict(target.tickers)
    marks: dict[str, Decimal] = {}
    visible = publication.visible_predicate("b")
    with conn.cursor() as cur:
        if security_ids:
            cur.execute(
                "SELECT security_id,ticker,close_unadjusted FROM sentinel_bars b"
                " WHERE session=%s AND security_id=ANY(%s) AND " + visible,
                (session, security_ids))
            for security_id, ticker, close in cur.fetchall():
                sid = str(security_id)
                tickers[sid] = str(ticker)
                if close is not None:
                    marks[sid] = Decimal(str(close))
        defensive_visible = publication.visible_predicate("d")
        cur.execute(
            "SELECT security_id,close_unadjusted FROM sentinel_defensive_bars d"
            " WHERE session=%s AND security_id=%s AND ticker=%s AND "
            + defensive_visible,
            (session, DEFENSIVE_SECURITY_ID, DEFENSIVE_SYMBOL))
        defensive = cur.fetchall()
    if defensive and defensive[0][1] is not None:
        marks[DEFENSIVE_SECURITY_ID] = Decimal(str(defensive[0][1]))
    tickers[DEFENSIVE_SECURITY_ID] = DEFENSIVE_SYMBOL
    return marks, tickers

def _fresh_warmed_state(conn, *, through: str, count: int,
                        account: BrokerAccountSnapshot,
                        controller_config: ControllerConfig,
                        strategy_identity: Mapping,
                        publication_version: int,
                        authorization_mode: str = "HISTORICALLY_CERTIFIED",
                        ) -> SessionState:
    sessions = calendar.previous_sessions(through, count + 1)
    if len(sessions) != count + 1 or sessions[-1] != through:
        raise PaperActivationRefused(
            f"fresh start needs {count} XNYS sessions strictly before {through}; "
            f"the calendar supplied {max(0, len(sessions) - 1)}")
    warm = sessions[:-1]
    window = load_window(conn, start=warm[0], end=warm[-1])
    if window.sessions != warm:
        missing = sorted(set(warm) - set(window.sessions))
        raise PaperActivationRefused(
            f"the pinned warm-up window is incomplete: {missing[:8]}")
    prospective_witness = False
    if is_concordance_identity(strategy_identity):
        try:
            window.metadata_timeline = load_causal_meta_history(
                conn, sessions=warm)
        except CausalMetadataUnavailable as exc:
            if authorization_mode != PAPER_OBSERVATION_ONLY:
                raise PaperActivationRefused(
                    "fresh Concordance activation requires session-effective "
                    "TICKERS metadata for every historical witness close") from exc
            # The signed observation mode makes no historical causality claim.
            # Prime price features only and begin the zero-capital witness on
            # the first current decision close; never backdate today's TICKERS
            # snapshot to manufacture r20/r40 readiness.
            prospective_witness = True
    starting_cash = float(account.equity)
    if not math.isfinite(starting_cash):
        raise PaperActivationRefused("account equity cannot be represented by Wealth Core")
    state = SessionState.fresh(
        starting_cash=starting_cash, controller=Controller(controller_config),
        strategy_identity=strategy_identity)
    return warm_session_state(
        state, window, publication_version=publication_version,
        prospective_concordance_witness=prospective_witness)

async def prepare_paper_plan(*, conn, broker: ExecutionBroker, base_url: str,
                             through: date | str,
                             expected_account: Optional[str] = None,
                             warmup_sessions: int = 252,
                             controller_config: ControllerConfig | None = None,
                             strategy_identity: Mapping | None = None,
                             now_et: datetime | None = None,
                             automation_grant: AutomationExecutionGrant | None = None,
                             automation_config_sha256: str | None = None,
                             dual_shadow_observation_id: str | None = None,
                             dual_shadow_starting_cash: Decimal | str | None = None,
                             ) -> PreparationResult:
    """Advance and adopt one current plan without any broker mutation."""
    assert_paper_url(base_url)
    _require_certified_paper_broker(broker)
    schema.require_runtime_schema(conn)
    try:
        journal.require_observation_integrity(conn)
    except journal.ObservationEvidenceUncertifiable as exc:
        raise PaperActivationRefused(str(exc)) from exc
    through_date = (through if isinstance(through, date)
                    else date.fromisoformat(str(through)))
    through_text = through_date.isoformat()
    if expected_account is None or not str(expected_account).strip():
        raise PaperActivationRefused(
            "paper preparation requires the exact expected account id")
    if (automation_grant is not None
            and automation_grant.operation_scope != "PREPARE"):
        raise PaperActivationRefused(
            "automation preparation requires a PREPARE-scoped grant")
    dual_values = (
        dual_shadow_observation_id, dual_shadow_starting_cash)
    if any(value is not None for value in dual_values) \
            and not all(value is not None for value in dual_values):
        raise PaperActivationRefused(
            "dual PAPER preparation requires both reviewed shadow identity "
            "and starting-capital configuration")
    dual_mode = all(value is not None for value in dual_values)
    # A reviewed deploy may perform this preparation through the read-only
    # PaperPreparationGrant while automation remains killed. That grant cannot
    # cross any broker mutation method. Actual informational transport remains
    # automation-only in `_execute_current_paper_plan`.
    if controller_config is None and strategy_identity is None:
        config, identity = _default_paper_strategy()
    else:
        # Preserve the explicit injection seam used by deterministic tests and
        # administrative tooling. Production supplies neither override.
        config = controller_config or load_controller()
        identity = dict(strategy_identity or runtime_strategy_identity(config))

    with journal.writer_lock(conn):
        # Ownership is checked under the same lock as plan adoption and before
        # the first broker read. An unbound inherited book is migration input,
        # never something daily preparation may adopt.
        from sentinel.handover import assert_no_legacy_path
        binding = assert_no_legacy_path(conn)
        rollout = load_rollout_state(conn)
        with publication.pinned(conn, commit=False) as pinned:
            observation_time = (now_et if now_et is not None else
                                datetime.now(ZoneInfo(calendar.EXCHANGE_TZ)))
            _readiness_or_refuse(conn, now_et=observation_time)
            latest_closed = calendar.latest_closed_session(observation_time)
            if through_text != latest_closed:
                raise PaperActivationRefused(
                    f"requested decision session {through_text} is not the "
                    f"latest closed XNYS session {latest_closed}. An early "
                    "current-session publication is not close evidence and "
                    "cannot become an immutable next-session plan.")
            frontier = feed_store.latest_visible_session(conn)
            if frontier != through_text:
                raise PaperActivationRefused(
                    f"requested decision session {through_text} is not the "
                    f"published frontier {frontier}")

            authority_kwargs = dict(
                runtime_identity=system_identity.rehearsal_identity(),
                strategy_identity=identity, required_mode=rollout.mode,
                paper_base_url=base_url,
                current_publication_version=pinned.version,
                automation_config_sha256=automation_config_sha256)
            if automation_grant is not None:
                automation_certificate = require_current_authority(
                    conn, required_operation="AUTOMATION", **authority_kwargs)
                certificate = require_current_authority(
                    conn, required_operation="PREPARE_READ", **authority_kwargs)
                if (automation_certificate.certificate_sha256
                        != certificate.certificate_sha256
                        or automation_grant.certificate_sha256
                        != certificate.certificate_sha256):
                    raise PaperActivationRefused(
                        "automation preparation grant and signed authority "
                        "do not match")
                grant = automation_grant
            else:
                certificate = require_current_authority(
                    conn, required_operation="PREPARE_READ", **authority_kwargs)
                grant = PaperPreparationGrant(
                    expected_account=str(expected_account),
                    decision_session=through_date)
            if (rollout.mode is RolloutMode.CONTROLLER
                    and rollout.certificate_sha256
                    != certificate.certificate_sha256):
                raise PaperActivationRefused(
                    "controller rollout and signed execution authority differ")
            if now_et is None:
                clock = lambda: datetime.now(ZoneInfo(calendar.EXCHANGE_TZ))
            else:
                clock = lambda: observation_time
            strategy_provider = (
                (lambda: _default_paper_strategy()[1])
                if controller_config is None and strategy_identity is None
                else lambda: dict(identity))
            broker = _guard_broker(
                conn=conn, broker=broker, grant=grant, base_url=base_url,
                now_provider=clock, strategy_provider=strategy_provider,
                automation_config_sha256=automation_config_sha256,
                dual_shadow_observation_id=dual_shadow_observation_id,
                dual_shadow_starting_cash=dual_shadow_starting_cash)

            existing_plan = journal.latest_plan(conn)
            dual_result = None
            dual_state = None
            if dual_mode:
                # Dual mode has one strategy lineage: the independently
                # attested shadow ledger.  Never even read the legacy PAPER
                # catch-up cursor, because a second path-dependent state could
                # drift while still producing plausible exposure numbers.
                from sentinel import dual_reconciliation
                try:
                    dual_result = dual_reconciliation.verified_shadow_intent(
                        conn, decision_session=through_date,
                        observation_id=str(dual_shadow_observation_id),
                        starting_cash=dual_shadow_starting_cash)
                except dual_reconciliation.DualReconciliationPending as exc:
                    raise PaperRetryableRefused(str(exc)) from exc
                except dual_reconciliation.DualReconciliationRefused as exc:
                    raise PaperActivationRefused(str(exc)) from exc
                dual_state = SessionState.from_dict(
                    dual_result.state.to_dict())
                if dual_state.strategy_identity != identity:
                    raise PaperActivationRefused(
                        "verified shadow strategy/config/source identity "
                        "differs from the PAPER adapter")
                if dual_state.data_version != pinned.version:
                    raise PaperRetryableRefused(
                        "verified shadow state does not name the exact pinned "
                        "publication used for PAPER account sizing")
                from sentinel import shadow_runtime
                not_before = shadow_runtime.publication_not_before(through_text)
                if observation_time < not_before:
                    raise PaperRetryableRefused(
                        "informational PAPER unit revalidation waits for the "
                        "reviewed source-final 23:45 New York boundary")
                try:
                    informational_paper_mirror.revalidate_all(
                        conn, checked_through=through_date,
                        publication_version=pinned.version, commit=True)
                    informational_paper_mirror.require_transport_permitted(
                        conn, current_frontier=through_date,
                        current_publication_version=pinned.version)
                except informational_paper_mirror.InformationalPaperMirrorMismatch as exc:
                    raise PaperActivationRefused(
                        f"informational PAPER mirror is blocked: {exc}") from exc
                except informational_paper_mirror.InformationalPaperMirrorPending as exc:
                    raise PaperRetryableRefused(
                        f"informational PAPER mirror is pending: {exc}") from exc
                except informational_paper_mirror.InformationalPaperMirrorRefused as exc:
                    raise PaperActivationRefused(
                        f"informational PAPER mirror is not current: {exc}") from exc
                existing_raw = None
                existing_cursor = None
            else:
                existing_raw = catchup.resume_state(conn)
                existing_cursor = catchup.last_processed_session(conn)
            if (existing_plan is not None
                    and existing_plan.decision_session == through_date):
                # Restart validation may return this plan unchanged. Prove its
                # economics still derive its id before contacting the broker.
                _assert_deterministic_plan_id(existing_plan)

            if (dual_mode and existing_plan is not None
                    and existing_plan.decision_session == through_date):
                state = dual_state
                _assert_concordance_witness_authority(
                    state, certificate.authorization_mode)
                _assert_plan_authorities(
                    conn, state=state, plan=existing_plan, binding=binding,
                    pinned=pinned, frontier=through_text,
                    today=date.fromisoformat(
                        calendar.next_session(through_text)),
                    runtime_identity=identity, rollout=rollout,
                    require_effective_today=False)
                try:
                    dual_plan_authority.rederive_plan(
                        conn, plan=existing_plan, binding=binding,
                        rollout_state=rollout,
                        expected_shadow_result=dual_result)
                except dual_plan_authority.DualPlanAuthorityRefused as exc:
                    raise PaperActivationRefused(
                        f"dual sizing authority refused restart: {exc}") from exc
                rec = await reconciliation.reconcile(
                    broker=broker, conn=conn, binding=None,
                    deployment=binding.identity,
                    actions=_action_lookup(conn, state, through_date))
                observation = _clean_or_refuse(
                    rec, purpose="dual PAPER preparation restart")
                account = await broker.account_snapshot()
                _account_or_refuse(account, binding, expected_account)
                activity_state = await _broker_cash_state_or_refuse(
                    conn, broker=broker, binding=binding,
                    through=observation_time)
                _cash_authority_or_refuse(
                    conn, plan=existing_plan, deployment=binding.identity,
                    account=account, observation=observation,
                    activity_state=activity_state)
                journal.adopt_current_plan(conn, existing_plan)
                return PreparationResult(
                    plan=existing_plan, sessions_replayed=0,
                    warmup_sessions=0, state_fingerprint=state.state_hash,
                    publication_version=pinned.version, frontier=through_text,
                    reconciliation=rec, superseded_plans=0)

            # Same-session preparation is restart validation, not a second
            # sizing decision. Re-reading a later NAV and replacing the plan
            # under the same market close would make an immutable daily intent
            # depend on how many times the operator retried it.
            if (existing_raw is not None and existing_cursor == through_date):
                state = SessionState.from_dict(existing_raw)
                _assert_concordance_witness_authority(
                    state, certificate.authorization_mode)
                if state.last_processed_session != existing_cursor.isoformat():
                    raise PaperActivationRefused(
                        "canonical state and processed-session cursor disagree")
                if state.strategy_identity != identity:
                    raise PaperActivationRefused(
                        "persisted strategy/config/source identity differs "
                        "from runtime")
                if existing_plan is None:
                    raise PaperActivationRefused(
                        "current state already names this session but has no "
                        "durable current plan")
                _assert_plan_authorities(
                    conn, state=state, plan=existing_plan, binding=binding,
                    pinned=pinned, frontier=through_text, today=date.fromisoformat(
                        calendar.next_session(through_text)),
                    runtime_identity=identity, rollout=rollout,
                    require_effective_today=False)
                rec = await reconciliation.reconcile(
                    broker=broker, conn=conn, binding=None,
                    deployment=binding.identity,
                    actions=_action_lookup(conn, state, through_date))
                observation = _clean_or_refuse(
                    rec, purpose="paper preparation restart")
                account = await broker.account_snapshot()
                _account_or_refuse(account, binding, expected_account)
                activity_state = await _broker_cash_state_or_refuse(
                    conn, broker=broker, binding=binding,
                    through=observation_time)
                _cash_authority_or_refuse(
                    conn, plan=existing_plan, deployment=binding.identity,
                    account=account, observation=observation,
                    activity_state=activity_state)
                # Repairs any legacy save/supersede crash shape without
                # changing plan economics; identical adoption is idempotent.
                journal.adopt_current_plan(conn, existing_plan)
                return PreparationResult(
                    plan=existing_plan, sessions_replayed=0,
                    warmup_sessions=0, state_fingerprint=state.state_hash,
                    publication_version=pinned.version, frontier=through_text,
                    reconciliation=rec, superseded_plans=0)

            actions = (
                _action_lookup(conn, dual_state, through_date)
                if dual_mode else
                _action_lookup(
                    conn, SessionState.from_dict(existing_raw), through_date)
                if existing_raw is not None else None)
            due_existing_cycle = (
                existing_plan is not None
                and trial.due_succeeded_cycle_id(
                    conn, plan_id=existing_plan.plan_id,
                    effective_session=existing_plan.effective_session)
                is not None)
            due_authority = None
            due_target_actions = None
            due_observation_target_actions = None
            if due_existing_cycle:
                _assert_deterministic_plan_id(existing_plan)
                due_target_actions = _target_action_lookup(
                    conn, existing_plan, existing_plan.effective_session)
                due_observation_target_actions = _target_action_lookup(
                    conn, existing_plan, through_date)
                commands = journal.load_commands(conn, binding.identity)
                active_security_ids = _preopen_active_security_ids(
                    plan=existing_plan, commands=commands, actions=actions)
                if active_security_ids and not dual_mode:
                    official_open = _official_preopen_cutoff(existing_plan)
                    due_authority, actions, due_target_actions = (
                        _preopen_views_or_none(
                            conn, plan=existing_plan,
                            active_security_ids=active_security_ids,
                            required_cutoff_at=official_open,
                            evaluated_at=clock(), actions=actions,
                            target_actions=due_target_actions))
                    if due_authority is None:
                        raise PreOpenShareUnitAuthorityUnavailable(
                            "pre-open share-unit authority is absent for a "
                            "nonempty succeeded-cycle finalization book; "
                            "Sentinel will not interpret prior-plan, command, "
                            "or broker-position units across its open")
                    due_observation_target_actions = (
                        preopen_authority.overlay_actions(
                            due_observation_target_actions, due_authority))

            rec = await reconciliation.reconcile(
                broker=broker, conn=conn, binding=None,
                deployment=binding.identity,
                actions=actions)
            if due_existing_cycle:
                current_commands = journal.load_commands(
                    conn, binding.identity)
                current_security_ids = _preopen_active_security_ids(
                    plan=existing_plan, commands=current_commands,
                    actions=actions)
                if (not dual_mode and due_authority is None
                        and current_security_ids):
                    raise PreOpenShareUnitAuthorityUnavailable(
                        "pre-open share-unit authority is absent after "
                        "succeeded-cycle reconciliation adopted a nonempty "
                        "share-unit identity")
                if due_authority is not None:
                    _revalidate_preopen_authority_or_refuse(
                        authority=due_authority, plan=existing_plan,
                        commands=current_commands, actions=actions,
                        required_cutoff_at=_official_preopen_cutoff(
                            existing_plan), evaluated_at=clock())
            observation = _clean_or_refuse(rec, purpose="paper preparation")
            account_observation_started_at = clock()
            account = await broker.account_snapshot()
            account_observed_at = clock()
            _account_or_refuse(account, binding, expected_account)
            activity_state = await _broker_cash_state_or_refuse(
                conn, broker=broker, binding=binding,
                through=account_observed_at)
            if existing_plan is not None:
                _cash_authority_or_refuse(
                    conn, plan=existing_plan, deployment=binding.identity,
                    account=account, observation=observation,
                    activity_state=activity_state,
                    permit_new_activity=True)
                if due_existing_cycle and not dual_mode:
                    await _finalize_due_succeeded_cycle_or_refuse(
                        conn, broker=broker, deployment=binding.identity,
                        plan=existing_plan, reconciliation=rec,
                        account=account, activity_state=activity_state,
                        observation_started_at=(
                            account_observation_started_at),
                        observed_at=account_observed_at,
                        target_actions=due_target_actions,
                        observation_target_actions=(
                            due_observation_target_actions),
                        clock=clock)
                # Informational dual PAPER deliberately has no PAPER trial-P/L
                # authority.  Its prior succeeded cycle therefore creates no
                # official-close/fill-finality debt before the next account-
                # sized plan.  The complete live account/reconciliation and
                # cash explanation above still gate sizing; certified return
                # remains solely in the independently verified shadow chain.
            if any(order.is_working for order in observation.orders):
                raise PaperActivationRefused(
                    "initial plan adoption requires no working broker order; "
                    "settle or explicitly resolve the prior durable command "
                    "before establishing the account-cash baseline")

            if dual_mode:
                # The shadow record has already advanced the only strategy
                # state.  This branch performs account sizing and plan adoption
                # only; it never reads or writes the PAPER catch-up cursor.
                state = dual_state
                _assert_concordance_witness_authority(
                    state, certificate.authorization_mode)
                marks, tickers = _load_marks_and_tickers(
                    conn, state, through_text)
                decision = build_execution_plan(
                    state=state, binding=binding, publication=pinned,
                    account_snapshot=account, observation=observation,
                    marks=marks, tickers=tickers,
                    decision_session=through_date,
                    effective_session=date.fromisoformat(
                        calendar.next_session(through_text)),
                    rollout_state=rollout)
                authority = dual_plan_authority.build_authority(
                    plan=decision.plan, shadow_result=dual_result,
                    publication=pinned, account_snapshot=account,
                    observation=observation, marks=marks, tickers=tickers)
                superseded = int(
                    existing_plan is not None
                    and existing_plan.plan_id != decision.plan.plan_id)
                latest = journal.adopt_current_plan(
                    conn, decision.plan, commit=False)
                dual_plan_authority.record_authority(
                    conn, authority, commit=False)
                dual_plan_authority.rederive_plan(
                    conn, plan=latest, binding=binding,
                    rollout_state=rollout,
                    expected_shadow_result=dual_result)
                if activity_state is not None:
                    try:
                        broker_cash.record_plan_baseline(
                            conn, plan_id=latest.plan_id,
                            decision_session=latest.decision_session,
                            activity_state=activity_state)
                    except broker_cash.BrokerCashAuthorityRefused as exc:
                        raise PaperActivationRefused(
                            "cannot establish immutable dual plan cash "
                            f"baseline: {exc}") from exc
                conn.commit()
                return PreparationResult(
                    plan=latest, sessions_replayed=0, warmup_sessions=0,
                    state_fingerprint=state.state_hash,
                    publication_version=pinned.version, frontier=through_text,
                    reconciliation=rec, superseded_plans=superseded)

            raw = existing_raw
            cursor = existing_cursor
            warmed = 0
            if raw is None:
                if cursor is not None:
                    raise PaperActivationRefused(
                        "processed-session cursor exists without canonical state")
                if (observation.positions
                        or any(order.is_working for order in observation.orders)):
                    raise PaperActivationRefused(
                        "canonical state is absent but the paper account is not "
                        "completely flat. Feature warm-up cannot reconstruct "
                        "path-dependent portfolio history; restore the state or "
                        "resolve the account explicitly")
                state = _fresh_warmed_state(
                    conn, through=through_text, count=warmup_sessions,
                    account=account, controller_config=config,
                    strategy_identity=identity,
                    publication_version=pinned.version,
                    authorization_mode=certificate.authorization_mode)
                _assert_concordance_witness_authority(
                    state, certificate.authorization_mode)
                warmed = warmup_sessions
            else:
                state = SessionState.from_dict(raw)
                _assert_concordance_witness_authority(
                    state, certificate.authorization_mode)
                if cursor is None or state.last_processed_session != cursor.isoformat():
                    raise PaperActivationRefused(
                        "canonical state and processed-session cursor disagree")
                if state.strategy_identity != identity:
                    raise PaperActivationRefused(
                        "persisted strategy/config/source identity differs from runtime")

            missed = _missed_sessions(cursor, through_date)
            if not missed and state.data_version != pinned.version:
                raise PaperActivationRefused(
                    "the corpus publication changed without a new decision "
                    "session; replaying path-dependent state in place is unsafe")

            def advance(c, session, prior):
                return advance_and_persist(
                    c, session, prior, load_published=load_published_session,
                    controller_config=config, strategy_identity=identity,
                    commit_pin=False)

            def decide(session, final_state):
                canonical = SessionState.from_dict(final_state)
                marks, tickers = _load_marks_and_tickers(
                    conn, canonical, session)
                result = build_execution_plan(
                    state=canonical, binding=binding,
                    publication=pinned, account_snapshot=account,
                    observation=observation, marks=marks, tickers=tickers,
                    decision_session=date.fromisoformat(session),
                    effective_session=date.fromisoformat(
                        calendar.next_session(session)),
                    rollout_state=rollout)
                return result.plan

            caught = catchup.catch_up_locked(
                conn, through=through_date, missed=missed,
                advance_state=advance, decide=decide, state=state.to_dict())
            final_state = SessionState.from_dict(caught.state)
            latest = journal.latest_plan(conn)
            if latest is None or latest.plan_id != caught.plan.plan_id:
                raise PaperActivationRefused(
                    "preparation did not leave exactly its plan current")
            _assert_deterministic_plan_id(latest)
            if activity_state is not None:
                try:
                    broker_cash.record_plan_baseline(
                        conn, plan_id=latest.plan_id,
                        decision_session=latest.decision_session,
                        activity_state=activity_state)
                except broker_cash.BrokerCashAuthorityRefused as exc:
                    raise PaperActivationRefused(
                        f"cannot establish immutable plan cash baseline: {exc}") from exc
            return PreparationResult(
                plan=latest, sessions_replayed=caught.sessions_replayed,
                warmup_sessions=warmed, state_fingerprint=final_state.state_hash,
                publication_version=pinned.version, frontier=through_text,
                reconciliation=rec, superseded_plans=caught.superseded)

def current_paper_plan(
        conn, *, base_url: str = DEFAULT_BASE_URL,
        dual_shadow_observation_id: str | None = None,
        dual_shadow_starting_cash: Decimal | str | None = None) -> dict:
    """Inspect current durable authorities without contacting the broker.

    Informational dual plans deliberately have no PAPER catch-up cursor: their
    only strategy state is the independently attested shadow record.  The dual
    inspection path therefore re-earns that record against the current corpus
    and re-derives the immutable account-sizing authority.  Ordinary PAPER
    keeps the historical strict catch-up-state inspection unchanged.
    """
    dual_values = (
        dual_shadow_observation_id, dual_shadow_starting_cash)
    if any(value is not None for value in dual_values) \
            and not all(value is not None for value in dual_values):
        raise PaperActivationRefused(
            "dual PAPER inspection requires both reviewed shadow identity "
            "and starting-capital configuration")
    dual_mode = all(value is not None for value in dual_values)
    dual_match = None
    if dual_mode:
        plan = journal.latest_plan(conn)
        if plan is None:
            raise PaperActivationRefused(
                "there is no durable current dual PAPER plan")
        _assert_deterministic_plan_id(plan)
        from sentinel import dual_reconciliation
        try:
            dual_match = dual_reconciliation.require_plan_matches_verified_shadow(
                conn, plan=plan,
                observation_id=str(dual_shadow_observation_id),
                starting_cash=dual_shadow_starting_cash)
            result = dual_reconciliation.verified_shadow_intent(
                conn, decision_session=plan.decision_session,
                observation_id=str(dual_shadow_observation_id),
                starting_cash=dual_shadow_starting_cash)
        except dual_reconciliation.DualReconciliationPending as exc:
            raise PaperRetryableRefused(str(exc)) from exc
        except dual_reconciliation.DualReconciliationRefused as exc:
            raise PaperActivationRefused(str(exc)) from exc
        state = SessionState.from_dict(result.state.to_dict())
        cursor = plan.decision_session
    else:
        state, plan, cursor = _state_and_plan_or_refuse(conn)
    from sentinel.handover import assert_no_legacy_path
    binding = assert_no_legacy_path(conn)
    current = publication.require_current(conn)
    frontier = feed_store.latest_visible_session(conn)
    _controller_config, runtime_identity = _default_paper_strategy()
    rollout = load_rollout_state(conn)
    checks = {
        "owned_binding": binding.is_owned,
        "state_matches_plan": state.state_hash == plan.shadow_snapshot_hash,
        "controller_transition_matches_plan": (
            _hash(state.last_decision) == plan.sentinel_transition_hash),
        "publication_matches_plan": (
            (dual_mode and dual_match is not None
             and state.data_version == plan.data_version)
            or (not dual_mode
                and state.data_version == plan.data_version == current.version
                and plan.publication_fingerprint
                == publication_fingerprint(current))),
        "account_matches_plan": (
            plan.deployment_id == binding.deployment_id
            and plan.broker == binding.broker
            and plan.broker_account_id == binding.broker_account_id
            and plan.takeover_epoch == binding.takeover_epoch),
        "strategy_matches_runtime": (
            (dual_mode and dual_match is not None
             and dual_match["state_sha256"] == state.state_hash)
            or (not dual_mode
                and state.strategy_identity == runtime_identity
                and _hash(state.strategy_identity)
                == plan.strategy_fingerprint)),
        "decision_matches_frontier": (
            state.last_processed_session
            == plan.decision_session.isoformat()
            == str(frontier)),
        "effective_is_next_session": (
            plan.effective_session.isoformat()
            == calendar.next_session(plan.decision_session)),
        "rollout_matches_plan": (
            plan.rollout_mode == rollout.mode.value
            and plan.rollout_version == rollout.version
            and plan.rollout_certificate_sha256
            == rollout.certificate_sha256
            and (rollout.mode is not RolloutMode.PINNED_1_00
                 or plan.target_exposure == Decimal(1))),
    }
    if dual_mode:
        checks.update({
            "current_corpus_shadow_revalidated": dual_match is not None,
            "dual_sizing_authority_matches": (
                dual_match is not None
                and dual_match.get("verdict") == "MATCH"),
            "dual_plan_fingerprint_matches": (
                dual_match is not None
                and dual_match.get("plan_fingerprint")
                == plan.fingerprint()),
        })
    try:
        certificate = require_current_authority(
            conn, runtime_identity=system_identity.rehearsal_identity(),
            strategy_identity=runtime_identity, required_mode=rollout.mode,
            required_operation="EXECUTE_READ", paper_base_url=base_url,
            current_publication_version=current.version)
        checks["system_certificate_valid"] = (
            rollout.mode is not RolloutMode.CONTROLLER
            or rollout.certificate_sha256 == certificate.certificate_sha256)
    except AuthorityRefused:
        checks["system_certificate_valid"] = False
    return {
        "broker_contacted": False,
        "broker_mutations_permitted": False,
        # Broker account, current NAV, readiness, reconciliation, actual date,
        # and asset tradability are intentionally rechecked only by execution.
        "execution_authorized": False,
        "database_authorities_match": all(checks.values()),
        "mode": "INFORMATIONAL_PAPER_MIRROR" if dual_mode else "PAPER",
        "performance_authority": (
            "CERTIFIED_SHADOW" if dual_mode else "PAPER_TRIAL"),
        "dual_reconciliation": dual_match,
        "cursor": cursor.isoformat(),
        "frontier": frontier,
        "binding": binding.to_dict(),
        "publication": current.to_dict(),
        "rollout": rollout.to_dict(),
        "state_fingerprint": state.state_hash,
        "plan": plan.to_dict(),
        "checks": checks,
    }
