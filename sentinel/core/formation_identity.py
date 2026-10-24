"""Pure formation capital and complete economic warmup commitments."""
from __future__ import annotations
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from typing import Mapping
from sentinel.core.price_identity import ShadowObservationRefused, _exact_price_ratio, _signal_price_identity

WARMUP_SESSIONS = 252
WARMUP_INPUT_SCHEMA = 'sentinel.shadow-warmup-economic-input/2'


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
        window, sessions: list[str], *, prospective_witness: bool,
        expected_sessions: int = WARMUP_SESSIONS) -> dict:
    """Compact exact economic identity of every input that creates the seed."""
    ordered = [str(session) for session in sessions]
    if (expected_sessions not in (252, 299) or len(ordered) != expected_sessions
            or window.sessions != ordered
            or any(left >= right for left, right in zip(ordered, ordered[1:]))):
        raise ShadowRuntimeRefused(
            "shadow warm-up identity requires the selected feature-session axis")

    signal_anchors = {}
    if hasattr(window, "median5_spy_closes"):
        spy = window.median5_spy_closes
        if not isinstance(spy, Mapping) or set(spy) != set(ordered):
            raise ShadowRuntimeRefused("shadow warm-up requires the exact dated SPY history")
        if any(_decimal_text(spy[session], where=f"warm-up SPY close {session}",
                             positive=True) is None for session in ordered):
            raise ShadowRuntimeRefused("shadow warm-up requires positive SPY closes")
        for session in ordered:
            for bar in window.bars_by_session.get(session, ()):
                if bar.signal_close is not None:
                    signal_anchors.setdefault(bar.security_id, bar)

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
            **({"signal_close": _signal_price_identity(
                    bar, signal_anchors.get(bar.security_id), warmup=True),
                "raw_compatible_volume": volume}
               if hasattr(window, "median5_spy_closes") else {}),
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
        **({"median5_profile": "wealth-core-median5-v1",
            "median5_spy_sha256": _stream_sha256(
                (session, _exact_price_ratio(value, window.median5_spy_closes[ordered[0]]))
                for session, value in sorted(window.median5_spy_closes.items())),
            "median5_terminal_sha256": _stream_sha256(
                (s, sorted(ids)) for s, ids in sorted(window.median5_terminals.items()))}
           if hasattr(window, "median5_spy_closes") else {}),
        "schema": ('sentinel.shadow-window-warmup-input/1' if expected_sessions == 299 else WARMUP_INPUT_SCHEMA),
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
