"""Post-publication composition for the broker-free shadow observer.

This is the only runtime adapter around :mod:`sentinel.shadow_observation`.
It loads canonical Sharadar-published inputs under the corpus pin, constructs a
feature-only seed from explicit research capital, and appends one verified XNYS
session. It never constructs or receives a broker.
"""
from __future__ import annotations

import math
import os
import re
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, time as datetime_time, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping
from zoneinfo import ZoneInfo

from sentinel import identity as system_identity
from sentinel.controller import ldrc as ldrc_module
from sentinel.controller.concordance import is_concordance_identity
from sentinel.controller.concordance_parent import (
    STRATEGY_ID as CONCORDANCE_PARENT_STRATEGY_ID,
    load as load_concordance_parent,
)
from sentinel.controller.ldrc import LDRCConfig
from sentinel.controller.machine import Controller
from sentinel.core.loader import (
    CausalMetadataUnavailable,
    load_causal_meta_history,
    load_window,
)
from sentinel.core.decision import (
    publication_fingerprint,
    runtime_strategy_identity,
)
from sentinel.core.production import (
    SessionState,
    warm_session_state,
)
from sentinel.feed import calendar, publication, readiness
from sentinel.feed import store as feed_store
from sentinel.shadow_observation import (
    BEFORE_NEXT_OPEN,
    PostgresShadowObservationStore,
    PostgresShadowRuntime,
    ShadowObservationRefused,
    ShadowObservationResult,
    ShadowObserver,
    SHADOW_CUTOFF_POLICY,
    SHADOW_EXECUTION_MODEL,
    SHADOW_WARMUP_SESSIONS,
    WARMUP_INPUT_SCHEMA,
)


WARMUP_SESSIONS = SHADOW_WARMUP_SESSIONS
SHADOW_PUBLICATION_TIMING_POLICY = (
    "SHARADAR_SEP_SFP_SECOND_UPDATE_PLUS_15M_2345_AMERICA_NEW_YORK_V1")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_OBJECT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_DATA_PUBLICATION_SCHEMA = "sentinel.data-publication-binding/1"
_WARMUP_IDENTITY_CACHE: dict[str, dict] = {}


class ShadowRuntimeRefused(ShadowObservationRefused):
    """The unattended shadow composition cannot preserve verified lineage."""


def _starting_cash(value: Decimal | str | int | float) -> Decimal:
    if isinstance(value, bool):
        raise ShadowRuntimeRefused(
            "shadow starting cash must be an explicit positive decimal")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ShadowRuntimeRefused(
            "shadow starting cash must be an explicit positive decimal") from exc
    if not amount.is_finite() or amount <= 0:
        raise ShadowRuntimeRefused(
            "shadow starting cash must be an explicit positive decimal")
    as_float = float(amount)
    if not math.isfinite(as_float) or Decimal(str(as_float)) != amount:
        raise ShadowRuntimeRefused(
            "shadow starting cash is not exactly representable by Wealth Core")
    return amount


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def publication_not_before(session: str) -> datetime:
    """Fixed source-valid not-before for one Sharadar decision session."""
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", str(session)) is None:
        raise ShadowRuntimeRefused("shadow decision session is malformed")
    try:
        session_date = datetime.strptime(str(session), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ShadowRuntimeRefused("shadow decision session is invalid") from exc
    return datetime.combine(
        session_date, datetime_time(23, 45),
        tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)


def _require_publication_not_before(
        session: str, *, now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ShadowRuntimeRefused("shadow runtime clock must be timezone-aware")
    observed = now.astimezone(timezone.utc)
    eligible = publication_not_before(session)
    if observed < eligible:
        raise ShadowRuntimeRefused(
            f"shadow session {session} is not source-final before reviewed "
            f"Sharadar not-before {eligible.isoformat()}")
    return eligible


def _data_publication_subject_sha256(current, visible_frontier: str) -> str:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", visible_frontier):
        raise ShadowRuntimeRefused(
            "live publication frontier is unavailable for reviewed binding")
    value = json.dumps({
        "schema": _DATA_PUBLICATION_SCHEMA,
        "publication_fingerprint": publication_fingerprint(current),
        "visible_frontier": visible_frontier,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False)
    return hashlib.sha256(
        b"sentinel-nas-subject/v1\0data_publication\0"
        + value.encode("utf-8")).hexdigest()


def _canonical_json(value) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False)


def _canonical_sha256(value) -> str:
    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


def _decimal_text(value, *, where: str, positive: bool = False,
                  nonnegative: bool = False) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ShadowRuntimeRefused(f"{where} is not a finite decimal")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ShadowRuntimeRefused(
            f"{where} is not a finite decimal") from exc
    if (not number.is_finite()
            or (positive and number <= 0)
            or (nonnegative and number < 0)):
        raise ShadowRuntimeRefused(
            f"{where} is outside its economic domain")
    return format(number.normalize(), "f")


def _stream_sha256(values) -> str:
    """Length-frame canonical rows so a large warm-up never becomes one blob."""
    digest = hashlib.sha256()
    for value in values:
        encoded = _canonical_json(value).encode("ascii")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _warmup_input_identity(
        window, sessions: list[str], *, prospective_witness: bool) -> dict:
    """Compact exact economic identity of every input that creates the seed."""
    ordered = [str(session) for session in sessions]
    if (len(ordered) != WARMUP_SESSIONS
            or window.sessions != ordered
            or any(left >= right for left, right in zip(ordered, ordered[1:]))):
        raise ShadowRuntimeRefused(
            "shadow warm-up identity requires the exact 252-session axis")

    def economic_bar(bar, *, session: str, index: int) -> dict:
        raw_close = _decimal_text(
            bar.raw_close, where=f"warm-up raw close {session}/{index}",
            positive=True)
        raw_open = _decimal_text(
            bar.raw_open, where=f"warm-up raw open {session}/{index}",
            positive=True)
        volume = _decimal_text(
            bar.volume, where=f"warm-up volume {session}/{index}",
            nonnegative=True)
        liquidity = None
        if raw_close is not None and volume is not None:
            liquidity = format(
                (Decimal(raw_close) * Decimal(volume)).normalize(), "f")
        return {
            "security_id": str(bar.security_id),
            "ticker": str(bar.ticker),
            "raw_close": raw_close,
            "raw_open": raw_open,
            # Stored volume is already in raw-compatible shares.  This product
            # is exactly SEP.close * source volume, so a later split's inverse
            # close/volume rescale cannot change the committed liquidity.
            "raw_dollar_liquidity": liquidity,
            "split_ratio": _decimal_text(
                bar.split_ratio,
                where=f"warm-up split ratio {session}/{index}",
                positive=True),
            "dividend_per_share": _decimal_text(
                bar.dividend_per_share,
                where=f"warm-up dividend {session}/{index}",
                nonnegative=True),
            "tradeable": bool(bar.tradeable),
            "unresolved_corporate_action": bool(
                bar.unresolved_corporate_action),
        }

    def bar_rows():
        for session in ordered:
            bars = sorted(
                window.bars_by_session.get(session, ()),
                key=lambda item: (str(item.security_id), str(item.ticker)))
            yield {
                "session": session,
                "bars": [economic_bar(bar, session=session, index=index)
                         for index, bar in enumerate(bars)],
            }

    if prospective_witness:
        metadata_mode = "PROSPECTIVE_STATIC_FEATURE_METADATA"
        metadata_values = [{
            "security_id": str(security_id),
            "metadata": asdict(meta),
        } for security_id, meta in sorted(window.meta.items())]
    else:
        timeline = window.metadata_timeline
        if timeline is None or list(timeline.sessions) != ordered:
            raise ShadowRuntimeRefused(
                "causal shadow warm-up lacks its exact metadata timeline")
        metadata_mode = "CAUSAL_METADATA_TIMELINE"
        metadata_values = ({
            "session": session,
            "rows": [timeline.canonical_row(session, bar.security_id)
                     for bar in sorted(
                         window.bars_by_session.get(session, ()),
                         key=lambda item: (
                             str(item.security_id), str(item.ticker)))],
        } for session in ordered)

    identity = {
        "schema": WARMUP_INPUT_SCHEMA,
        "first_warmup_session": ordered[0],
        "last_warmup_session": ordered[-1],
        "session_count": len(ordered),
        "sessions_sha256": _canonical_sha256(ordered),
        "bars_sha256": _stream_sha256(bar_rows()),
        "metadata_mode": metadata_mode,
        "metadata_sha256": _stream_sha256(metadata_values),
    }
    identity["warmup_input_sha256"] = _canonical_sha256(identity)
    return json.loads(_canonical_json(identity))


def _load_warmup_material(
        conn, *, first_session: str, strategy_identity: Mapping):
    sessions = calendar.previous_sessions(first_session, WARMUP_SESSIONS + 1)
    if (len(sessions) != WARMUP_SESSIONS + 1
            or sessions[-1] != first_session):
        raise ShadowRuntimeRefused(
            f"shadow start needs {WARMUP_SESSIONS} complete XNYS sessions "
            f"before {first_session}")
    warm = sessions[:-1]
    window = load_window(conn, start=warm[0], end=warm[-1])
    if window.sessions != warm:
        missing = sorted(set(warm) - set(window.sessions))
        raise ShadowRuntimeRefused(
            "shadow feature warm-up is incomplete: " + ", ".join(missing[:8]))

    prospective_witness = False
    if is_concordance_identity(strategy_identity):
        try:
            window.metadata_timeline = load_causal_meta_history(
                conn, sessions=warm)
        except CausalMetadataUnavailable:
            # Do not backdate today's TICKERS snapshot. The retained strategy
            # supports a prospective zero-capital witness specifically for
            # forward observation; the first current close begins that witness.
            prospective_witness = True

    identity = _warmup_input_identity(
        window, warm, prospective_witness=prospective_witness)
    return window, prospective_witness, identity


def _fresh_seed(conn, *, first_session: str, starting_cash: Decimal,
                controller_config, strategy_identity: Mapping,
                publication_version: int) -> tuple[SessionState, dict]:
    window, prospective_witness, identity = _load_warmup_material(
        conn, first_session=first_session,
        strategy_identity=strategy_identity)
    seed = SessionState.fresh(
        starting_cash=float(starting_cash),
        controller=Controller(controller_config),
        strategy_identity=strategy_identity)
    warmed = warm_session_state(
        seed, window, publication_version=publication_version,
        prospective_concordance_witness=prospective_witness)
    return warmed, identity


def _current_warmup_input_identity(
        conn, *, first_session: str, strategy_identity: Mapping) -> dict:
    _window, _prospective, identity = _load_warmup_material(
        conn, first_session=first_session,
        strategy_identity=strategy_identity)
    return identity


def _warmup_loader(conn, observer: ShadowObserver):
    def load() -> dict:
        current = publication.current(conn)
        if current is None:
            raise ShadowRuntimeRefused(
                "current publication is unavailable for warm-up revalidation")
        info = getattr(conn, "info", None)
        dsn = str(getattr(conn, "dsn", "") or getattr(info, "dsn", ""))
        key = _canonical_sha256({
            "database_sha256": hashlib.sha256(
                dsn.encode("utf-8")).hexdigest(),
            "publication": current.to_dict(),
            "first_session": observer.first_session,
            "strategy_identity": observer.strategy_identity,
            "warmup_input_identity_sha256": (
                observer.warmup_input_identity_sha256),
        })
        cached = _WARMUP_IDENTITY_CACHE.get(key)
        if cached is not None:
            return json.loads(_canonical_json(cached))
        identity = _current_warmup_input_identity(
            conn, first_session=observer.first_session,
            strategy_identity=observer.strategy_identity)
        # The dedicated service needs at most the current and immediately prior
        # publication. Bound process memory and make a new publication evict old
        # identities rather than accumulating one entry per day indefinitely.
        if len(_WARMUP_IDENTITY_CACHE) >= 4:
            _WARMUP_IDENTITY_CACHE.clear()
        _WARMUP_IDENTITY_CACHE[key] = json.loads(_canonical_json(identity))
        return identity

    return load


def _strategy():
    # One shared composition asserts the exact hardened parent and retained
    # Simplified Concordance LD-RC overlay. No second strategy identity is
    # allowed to drift into the shadow path.
    if (ldrc_module.STRATEGY_ID
            != "sentinel-concordance-simplified-ldrc"
            or ldrc_module.STRATEGY_VERSION != 3):
        raise ShadowRuntimeRefused(
            "shadow runtime requires Simplified Concordance LD-RC v3")
    ldrc = LDRCConfig()
    actual = (
        ldrc.divergence_ceiling, ldrc.wc_drawdown_trigger,
        ldrc.recent_r20_trigger, ldrc.spy_r20_floor,
        ldrc.recovery_sessions, ldrc.spy_v_rebound,
    )
    if actual != (0.55, -0.10, -0.08, 0.00, 7, 0.11):
        raise ShadowRuntimeRefused(
            "Simplified LD-RC v3 constants differ from the retained strategy")
    controller = load_concordance_parent()
    if controller.strategy_id != CONCORDANCE_PARENT_STRATEGY_ID:
        raise ShadowRuntimeRefused(
            "shadow controller differs from the hardened Concordance parent")
    try:
        identity = runtime_strategy_identity(controller, concordance=True)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ShadowRuntimeRefused(
            "the complete shadow strategy/data semantics source bundle cannot "
            "be fingerprinted") from exc
    return controller, identity


def _validated_runtime_identity(
        *, observation_id: str, starting_cash: Decimal) -> dict:
    """Bind this process to the source identity certified before deployment."""
    expected = os.environ.get(
        "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256", "").strip()
    if not _HEX64.fullmatch(expected):
        raise ShadowRuntimeRefused(
            "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256 is required for shadow "
            "observation")
    current = system_identity.rehearsal_identity()
    actual = str(current.get("identity_hash") or "")
    environment = current.get("environment") or {}
    artifacts = current.get("deployment_artifacts") or {}
    git_commit = str(artifacts.get("git_commit") or "")
    runtime_image_digest = str(
        artifacts.get("runtime_image_digest") or "")
    sentinel_source = environment.get("sentinel_source") or {}
    wealth_source = environment.get("wealth_core_source") or {}
    sentinel_sha = str(sentinel_source.get("hash") or "")
    wealth_sha = str(wealth_source.get("hash") or "")
    if (actual != expected
            or environment.get("compatible") is not True
            or not _GIT_OBJECT.fullmatch(git_commit)
            or not _IMAGE_DIGEST.fullmatch(runtime_image_digest)
            or not _HEX64.fullmatch(sentinel_sha)
            or not _HEX64.fullmatch(wealth_sha)):
        raise ShadowRuntimeRefused(
            "running source/runtime identity differs from the exact validated "
            "deployment identity")
    reviewed_config = {
        "schema": "sentinel.shadow-reviewed-config/1",
        "observation_id": str(observation_id),
        "starting_cash": format(starting_cash.normalize(), "f"),
        "execution_model": SHADOW_EXECUTION_MODEL,
        "cutoff_policy": SHADOW_CUTOFF_POLICY,
        "publication_timing_policy": SHADOW_PUBLICATION_TIMING_POLICY,
        "validated_source_identity_sha256": expected,
    }
    encoded = json.dumps(
        reviewed_config, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode("ascii")
    reviewed_sha = hashlib.sha256(encoded).hexdigest()
    configured_sha = os.environ.get(
        "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256", "").strip()
    if configured_sha != reviewed_sha:
        raise ShadowRuntimeRefused(
            "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256 does not authorize this "
            "exact observation id/capital/model/source configuration")
    data_publication_sha = os.environ.get(
        "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256", "").strip()
    if not _HEX64.fullmatch(data_publication_sha):
        raise ShadowRuntimeRefused(
            "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256 is required for "
            "reviewed shadow genesis")
    return {
        "schema": "sentinel.shadow-runtime-identity/1",
        "validated_source_identity_sha256": expected,
        "environment_identity_sha256": actual,
        "sentinel_source_sha256": sentinel_sha,
        "wealth_core_source_sha256": wealth_sha,
        "git_commit": git_commit,
        "runtime_image_digest": runtime_image_digest,
        "validated_shadow_config_sha256": reviewed_sha,
        "validated_data_publication_sha256": data_publication_sha,
        "reviewed_shadow_config": reviewed_config,
    }


def _resume(store, *, observation_id: str, starting_cash: Decimal,
            controller_config, strategy_identity, runtime_identity):
    genesis = store.genesis()
    if genesis is None:
        return None
    first_session = genesis.get("first_session")
    if not isinstance(first_session, str):
        raise ShadowRuntimeRefused(
            "shadow genesis does not contain a first XNYS session")
    return ShadowObserver.resume(
        store=store, observation_id=observation_id,
        starting_cash=starting_cash, first_session=first_session,
        controller_config=controller_config,
        strategy_identity=strategy_identity,
        runtime_identity=runtime_identity)


def _require_reviewed_genesis_publication(
        conn, *, current, first_session: str,
        runtime_identity: Mapping) -> None:
    visible = feed_store.latest_visible_session(conn)
    if visible != first_session:
        raise ShadowRuntimeRefused(
            "first shadow session is not the exact live published frontier: "
            f"requested={first_session!r}, visible={visible!r}")
    actual = _data_publication_subject_sha256(current, visible)
    if actual != runtime_identity.get(
            "validated_data_publication_sha256"):
        raise ShadowRuntimeRefused(
            "live publication fingerprint/frontier differs from the reviewed "
            "shadow genesis binding")


def _require_fresh_genesis_authority(
        conn, *, current, first_session: str,
        runtime_identity: Mapping) -> dict:
    """Prove a warm seed is being born on the exact live ready corpus."""
    publication.assert_operationally_coherent(
        conn, frontier=first_session)
    if publication.chain_gaps(conn):
        raise ShadowRuntimeRefused(
            "corpus publication chain has gaps; shadow genesis refused")
    if (not isinstance(current.window_end, str)
            or current.window_end < first_session):
        raise ShadowRuntimeRefused(
            f"held publication does not cover first shadow session "
            f"{first_session}")
    _require_reviewed_genesis_publication(
        conn, current=current, first_session=first_session,
        runtime_identity=runtime_identity)
    result = readiness.check_readiness(conn)
    if not result.ready:
        failures = [str(check.name) for check in result.failures]
        raise ShadowRuntimeRefused(
            "canonical data readiness failed before shadow genesis: "
            + ", ".join(failures[:10]))
    execution_session = calendar.next_session(first_session)
    execution_open, _close = calendar.session_window(execution_session)
    execution_open = execution_open.astimezone(timezone.utc)
    observed_at = _utcnow().astimezone(timezone.utc)
    if observed_at >= execution_open:
        raise ShadowRuntimeRefused(
            f"first shadow session {first_session} is too late to commit before "
            f"its following XNYS open {execution_open.isoformat()}")
    return {
        "schema": "sentinel.shadow-activation-timing/1",
        "decision_session": first_session,
        "execution_session": execution_session,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "execution_open_at": execution_open.isoformat().replace("+00:00", "Z"),
        "status": BEFORE_NEXT_OPEN,
    }


def _advance_ready_shadow(
        conn, *, through: str, observation_id: str,
        starting_cash: Decimal | str | int | float) -> ShadowObservationResult:
    """Append or exactly revalidate one fully published decision session.

    A missed session is a permanent gap in point-in-time publication evidence;
    this function refuses rather than replaying it from today's restated corpus.
    """
    amount = _starting_cash(starting_cash)
    _require_publication_not_before(through, now=_utcnow())
    controller_config, strategy_identity = _strategy()
    runtime_identity = _validated_runtime_identity(
        observation_id=observation_id, starting_cash=amount)
    store = PostgresShadowObservationStore(
        conn, observation_id=observation_id)
    observer = _resume(
        store, observation_id=observation_id, starting_cash=amount,
        controller_config=controller_config,
        strategy_identity=strategy_identity,
        runtime_identity=runtime_identity)

    try:
        if observer is None:
            # The outer pin spans validation, warm-state construction, durable
            # genesis, and the runtime's nested authoritative first advance.
            # A publisher therefore cannot change the seed's corpus between
            # any of those steps.
            with publication.pinned(conn, commit=False) as current:
                activation_timing = _require_fresh_genesis_authority(
                    conn, current=current, first_session=through,
                    runtime_identity=runtime_identity)
                seed, warmup_input_identity = _fresh_seed(
                    conn, first_session=through, starting_cash=amount,
                    controller_config=controller_config,
                    strategy_identity=strategy_identity,
                    publication_version=current.version)
                observer = ShadowObserver(
                    store=store, observation_id=observation_id,
                    starting_cash=amount, first_session=through,
                    initial_state=seed, controller_config=controller_config,
                    strategy_identity=strategy_identity,
                    runtime_identity=runtime_identity,
                    activation_timing=activation_timing,
                    warmup_input_identity=warmup_input_identity)
                return PostgresShadowRuntime(
                    conn, observer=observer,
                    clock=_utcnow,
                    # This identity was loaded canonically under the same outer
                    # publication pin that remains held through first authority.
                    warmup_input_loader=lambda: warmup_input_identity,
                ).advance_through(through)

        if not store.records():
            # Genesis is committed before the first candidate. Keep the
            # reviewed publication pin held across crash recovery so a
            # re-publication cannot change the warm seed's first transition.
            with publication.pinned(conn, commit=False) as current:
                _require_reviewed_genesis_publication(
                    conn, current=current, first_session=through,
                    runtime_identity=runtime_identity)
                return PostgresShadowRuntime(
                    conn, observer=observer,
                    clock=_utcnow,
                    warmup_input_loader=_warmup_loader(conn, observer),
                ).advance_through(through)
        return PostgresShadowRuntime(
            conn, observer=observer,
            clock=_utcnow,
            warmup_input_loader=_warmup_loader(conn, observer),
        ).advance_through(through)
    except ShadowRuntimeRefused:
        raise
    except ShadowObservationRefused as exc:
        raise ShadowRuntimeRefused(str(exc)) from exc


def _verified_shadow_status(
        conn, *, observation_id: str,
        starting_cash: Decimal | str | int | float
        ) -> ShadowObservationResult | None:
    """Verify the entire retained chain and return its local performance."""
    amount = _starting_cash(starting_cash)
    controller_config, strategy_identity = _strategy()
    runtime_identity = _validated_runtime_identity(
        observation_id=observation_id, starting_cash=amount)
    store = PostgresShadowObservationStore(
        conn, observation_id=observation_id)
    observer = _resume(
        store, observation_id=observation_id, starting_cash=amount,
        controller_config=controller_config,
        strategy_identity=strategy_identity,
        runtime_identity=runtime_identity)
    if observer is None:
        return None
    if not store.records():
        return None
    try:
        return PostgresShadowRuntime(
            conn, observer=observer,
            clock=_utcnow,
            warmup_input_loader=_warmup_loader(conn, observer),
        ).durable_status()
    except ShadowRuntimeRefused:
        raise
    except ShadowObservationRefused as exc:
        raise ShadowRuntimeRefused(str(exc)) from exc


def _classify_shadow_lineage(
        conn, *, observation_id: str,
        starting_cash: Decimal | str | int | float,
        clock=None, structural_only: bool = False) -> dict:
    """Classify retained state without hiding a recoverable crash remnant.

    A candidate row is deliberately not a verified performance result.  The
    only non-fatal partial state is either a validated committed genesis or one
    structurally valid trailing candidate whose following XNYS open is still
    in the future.  The caller must immediately pass that exact session back
    through :func:`advance_ready_shadow`, which re-earns every live
    publication/readiness/input gate before publishing runtime authority.
    """
    amount = _starting_cash(starting_cash)
    controller_config, strategy_identity = _strategy()
    runtime_identity = _validated_runtime_identity(
        observation_id=observation_id, starting_cash=amount)
    store = PostgresShadowObservationStore(
        conn, observation_id=observation_id)
    genesis = store.genesis()
    if genesis is None:
        if store.records() or store.authorities():
            raise ShadowRuntimeRefused(
                "shadow rows exist without immutable genesis")
        return {"status": "NOT_STARTED"}
    observer = _resume(
        store, observation_id=observation_id, starting_cash=amount,
        controller_config=controller_config,
        strategy_identity=strategy_identity,
        runtime_identity=runtime_identity)
    if observer is None:  # pragma: no cover - genesis was proved above
        raise ShadowRuntimeRefused("shadow genesis could not be resumed")
    runtime = PostgresShadowRuntime(
        conn, observer=observer, clock=clock or _utcnow,
        warmup_input_loader=_warmup_loader(conn, observer))
    try:
        rows, _state, authorities = runtime._candidate_history()
        if not rows or len(rows) == len(authorities) + 1:
            # Genesis is intentionally committed before the first candidate.
            # A process crash in that small window is safe to resume only for
            # the exact configured first session and only before its cutoff.
            session = (observer.first_session if not rows
                       else rows[-1]["session"])
            execution_session, _observed, cutoff = \
                runtime._preopen_timing(session)
            return {
                "status": "RECOVERY_REQUIRED",
                "recovery_kind": (
                    "GENESIS_ONLY" if not rows else "TRAILING_CANDIDATE"),
                "recovery_session": session,
                "execution_session": execution_session,
                "recovery_cutoff_at": cutoff.astimezone(
                    timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        if len(rows) != len(authorities):
            raise ShadowRuntimeRefused(
                "shadow candidate/authority history is incoherent")
        if structural_only:
            if not rows:
                raise ShadowRuntimeRefused(
                    "attested shadow lineage has no published session")
            # This is intentionally not a performance verdict. It proves only
            # immutable genesis/record/runtime-authority structure so the
            # service may ingest the exactly-next close. Full corpus readiness,
            # warm-up/history revision equivalence and SHADOW_GO are re-earned
            # under the post-ingest pin by advance_ready_shadow.
            return {
                "status": "ATTESTED_STRUCTURAL",
                "latest_session": rows[-1]["session"],
            }
        result = runtime.durable_status()
        return {"status": "VERIFIED", "result": result}
    except ShadowRuntimeRefused:
        raise
    except ShadowObservationRefused as exc:
        raise ShadowRuntimeRefused(str(exc)) from exc


def advance_ready_shadow(
        conn, *, through: str, observation_id: str,
        starting_cash: Decimal | str | int | float) -> ShadowObservationResult:
    """Public fail-closed wrapper for one authoritative observation wake."""
    try:
        return _advance_ready_shadow(
            conn, through=through, observation_id=observation_id,
            starting_cash=starting_cash)
    except ShadowRuntimeRefused:
        raise
    except Exception as exc:
        raise ShadowRuntimeRefused(
            f"shadow runtime refused: {type(exc).__name__}: {exc}") from exc


def verified_shadow_status(
        conn, *, observation_id: str,
        starting_cash: Decimal | str | int | float
        ) -> ShadowObservationResult | None:
    """Public fail-closed wrapper for durable attested performance status."""
    try:
        return _verified_shadow_status(
            conn, observation_id=observation_id,
            starting_cash=starting_cash)
    except ShadowRuntimeRefused:
        raise
    except Exception as exc:
        raise ShadowRuntimeRefused(
            f"shadow status refused: {type(exc).__name__}: {exc}") from exc


def classify_shadow_lineage(
        conn, *, observation_id: str,
        starting_cash: Decimal | str | int | float,
        clock=None, structural_only: bool = False) -> dict:
    """Public read-only classifier for service/deployment restart routing."""
    try:
        return _classify_shadow_lineage(
            conn, observation_id=observation_id,
            starting_cash=starting_cash, clock=clock,
            structural_only=structural_only)
    except ShadowRuntimeRefused:
        raise
    except Exception as exc:
        raise ShadowRuntimeRefused(
            f"shadow lineage refused: {type(exc).__name__}: {exc}") from exc


__all__ = [
    "SHADOW_PUBLICATION_TIMING_POLICY", "ShadowRuntimeRefused",
    "WARMUP_SESSIONS", "advance_ready_shadow", "classify_shadow_lineage",
    "publication_not_before", "verified_shadow_status",
]
