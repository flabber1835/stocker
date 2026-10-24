"""Small display projections; no broker, strategy transition or write path."""
from collections.abc import Mapping
from sentinel.panel import model


def shadow_slots(wealth):
    """Preserve canonical slot identities and counters, never invent vacancies."""
    from stock_strategy_shared.wealth_core.state import COOLDOWN_SESSIONS

    slots = wealth.get('slots')
    if slots is None:
        return []  # Older display payload: explicitly unavailable to the renderer.
    if not isinstance(slots, Mapping) or not 0 < len(slots) <= 100:
        raise ValueError('canonical slots are missing or outside display bounds')
    episodes = wealth.get('episodes')
    if not isinstance(episodes, Mapping):
        raise ValueError('canonical episodes are unavailable')
    projected = []
    for key, slot in slots.items():
        if not isinstance(slot, Mapping) or type(slot.get('slot_id')) is not int:
            raise ValueError('canonical slot identity is invalid')
        slot_id = slot['slot_id']
        if str(slot_id) != str(key):
            raise ValueError('canonical slot key and identity disagree')
        occupied, reserved = slot.get('occupied_by'), slot.get('reserved_for')
        elapsed = slot.get('cooldown_sessions_elapsed')
        if elapsed is not None and (type(elapsed) is not int or not 0 <= elapsed < COOLDOWN_SESSIONS):
            raise ValueError('canonical slot cooldown is invalid')
        episode = episodes.get(str(slot_id), episodes.get(slot_id))
        values = dict(slot_id=slot_id, cooldown_total=COOLDOWN_SESSIONS)
        if occupied is not None:
            if (reserved is not None or elapsed is not None or not isinstance(episode, Mapping)
                    or episode.get('security_id') != occupied or episode.get('slot_id') != slot_id):
                raise ValueError('canonical slot and holding ownership disagree')
            values.update(state='OCCUPIED', security_id=occupied, ticker=episode.get('ticker'),
                model_quantity=episode.get('current_shares'),
                exit_pending=episode.get('exit_pending', False),
                exit_reason=episode.get('exit_reason'))
        elif episode is not None:
            raise ValueError('empty canonical slot has a holding episode')
        elif reserved is not None:
            if elapsed is not None:
                raise ValueError('reserved canonical slot is also cooling')
            values.update(state='RESERVED', security_id=reserved, ticker=slot.get('reserved_ticker'))
        elif elapsed is not None:
            values.update(state='COOLING', cooldown_elapsed=elapsed,
                          cooldown_remaining=COOLDOWN_SESSIONS-elapsed)
        else:
            values.update(state='READY')
        projected.append(model.ShadowSlot(**values))
    projected.sort(key=lambda item: item.slot_id)
    if [item.slot_id for item in projected] != list(range(len(projected))):
        raise ValueError('canonical slot identities are missing or duplicated')
    if len(episodes) != sum(item.state == 'OCCUPIED' for item in projected):
        raise ValueError('canonical episodes exceed the occupied slots')
    return projected


def account_overview(account, *, expected_account_id):
    """Typed balance only after exact account matching; no shadow substitutions."""
    if not account or account.get('broker') != 'alpaca' or not expected_account_id:
        return None
    if account.get('account_id') != expected_account_id:
        return None
    return model.PaperAccountOverview(
        account_id=account['account_id'], equity=account['equity'], cash=account['cash'],
        buying_power=account['buying_power'], observed_at=account['observed_at'])


def order_outcomes(rows):
    """Validate exact durable command facts without inventing native reasons."""
    if len(rows) > 100:
        raise ValueError('previous paper order outcomes exceed display bounds')
    outcomes = []
    for raw in rows:
        value = model.PaperOrderOutcome(**dict(zip(
            ('security_id', 'ticker', 'client_key', 'broker_order_id', 'side',
             'quantity', 'filled_quantity', 'state', 'observed_at'), raw, strict=True)))
        outcomes.append(value)
    if len({item.security_id for item in outcomes}) != len(outcomes):
        raise ValueError('previous paper order outcomes duplicate a security')
    return outcomes
