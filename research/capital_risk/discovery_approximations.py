"""Explicit owner-approved diagnostic conventions; never financial authority."""
from __future__ import annotations

import ast
from copy import deepcopy
from fractions import Fraction
import hashlib
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from system_campaign_discovery_context import TAINT, digest, material, need


class DiscoveryPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.owner-discovery-approximations/1'] = 'research.owner-discovery-approximations/1'
    authority: Literal['DISCOVERY_ONLY_NOT_FINANCIAL_AUTHORITY'] = TAINT
    arm: Literal['P09', 'P11']
    owner_approved: Literal[True] = True
    financial_authority: Literal[False] = False
    account_performance_computed: Literal[False] = False
    maximum_share_decimal_places: int = Field(default=12, ge=0, le=12)
    native_risk_source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    implementation_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

    def commitment(self):
        body = self.model_dump(mode='json')
        return dict(policy=body, sha256=digest(body))


def exact_number(value):
    value = Fraction(value)
    number = float(value)
    if not math.isfinite(number) or Fraction(str(number)) != value:
        raise ValueError('REFUSED_TRIM_QUANTITY_REPRESENTATION')
    return number


def allocate_trim(holdings, target, *, exact=exact_number, maximum_places=12):
    """Preserve the holder target and every original quantity as exact fractions."""
    values = [(int(slot), Fraction(str(shares))) for slot, shares in holdings]
    need(values == sorted(values) and len({s for s, _ in values}) == len(values),
         'DIAGNOSTIC_ALLOCATION_UNIQUE_ORDERED_SLOTS')
    need(values and all(q >= 0 for _, q in values), 'DIAGNOSTIC_ALLOCATION_NONNEGATIVE_HOLDINGS')
    total = sum((q for _, q in values), Fraction())
    target = Fraction(target)
    need(total > 0 and target.denominator == 1 and 0 <= target < total,
         'DIAGNOSTIC_ALLOCATION_SAME_WHOLE_HOLDER_TARGET')
    need(type(maximum_places) is int and 0 <= maximum_places <= 12,
         'DIAGNOSTIC_ALLOCATION_BOUNDED_PRECISION')
    proposed = [(slot, before, before * target / total) for slot, before in values]

    def checked(retained):
        rows = []
        for (slot, before), remaining in zip(values, retained, strict=True):
            need(0 <= remaining <= before, 'DIAGNOSTIC_ALLOCATION_EPISODE_BOUNDS')
            sold = before - remaining
            remain_float, sold_float = exact(remaining), exact(sold)
            need(Fraction(str(remain_float)) + Fraction(str(sold_float)) == before,
                 'DIAGNOSTIC_ALLOCATION_EVERY_ORIGINAL_SHARE_CONSERVED')
            rows.append((slot, remain_float, sold_float))
        need(sum((Fraction(str(r)) for _, r, _ in rows), Fraction()) == target
             and sum((Fraction(str(q)) for _, _, q in rows), Fraction()) == total - target,
             'DIAGNOSTIC_ALLOCATION_EXACT_HOLDER_CONSERVATION')
        return rows

    try:
        rows = checked([r for _, _, r in proposed])
        return rows, dict(rounded=False, holder_before=str(total), holder_target=str(target))
    except ValueError as error:
        if str(error) != 'REFUSED_TRIM_QUANTITY_REPRESENTATION':
            raise
    for places in range(maximum_places, -1, -1):
        units = 10 ** places
        wanted = int(target * units)
        quotas = [before * wanted / total for _, before in values]
        counts = [q.numerator // q.denominator for q in quotas]
        capacity = [(before * units).numerator // (before * units).denominator for _, before in values]
        missing = wanted - sum(counts)
        order = sorted(range(len(values)), key=lambda i: (-(quotas[i] - counts[i]), values[i][0]))
        for index in order:
            if missing and counts[index] < capacity[index]:
                counts[index] += 1
                missing -= 1
        if missing:
            continue
        try:
            rows = checked([Fraction(n, units) for n in counts])
        except ValueError as error:
            if str(error) != 'REFUSED_TRIM_QUANTITY_REPRESENTATION':
                raise
            continue
        return rows, dict(rounded=True, decimal_places=places, quantum=str(Fraction(1, units)),
            holder_before=str(total), holder_target=str(target),
            allocations=[dict(slot=slot, original=str(before), exact_pro_rata=str(proposal),
                retained=str(Fraction(str(remain))), sold=str(Fraction(str(sold))))
                for (slot, before, proposal), (_, remain, sold) in zip(proposed, rows, strict=True)])
    raise ValueError('DIAGNOSTIC_NO_CONSERVING_REPRESENTABLE_ALLOCATION')


def trim_tree(source):
    """Change only allocation and its zero/no-op lot outcomes in the real planner."""
    fn, = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'trim_decisions']
    allocation, = [n for n in ast.walk(fn) if isinstance(n, ast.For)
                   and ast.unparse(n.target) == '(slot, ep)' and ast.unparse(n.iter) == 'episodes']
    expected = ast.parse('''for slot,ep in episodes:
    before=Fraction(str(ep.current_shares))
    residual=before*target/total
    remain,sold=exact_float(residual),exact_float(before-residual)
    plans.append((slot,ep,remain,sold))
''').body[0]
    need(ast.dump(allocation, include_attributes=False) == ast.dump(expected, include_attributes=False),
         'DIAGNOSTIC_EXACT_ORIGINAL_PRO_RATA_PLANNER_SITE')
    class Allocate(ast.NodeTransformer):
        def visit_For(self, node):
            if node is allocation:
                return ast.copy_location(ast.parse('plans=diagnostic_plan(episodes,target,total)').body[0], node)
            return self.generic_visit(node)
    fn = Allocate().visit(fn)
    application, = [n for n in ast.walk(fn) if isinstance(n, ast.For)
                    and ast.unparse(n.target) == '(slot, ep, remain, sold)' and ast.unparse(n.iter) == 'plans']
    zero, = [n for n in application.body if isinstance(n, ast.If) and ast.unparse(n.test) == 'target == 0']
    zero.test = ast.parse('remain == 0', mode='eval').body
    application.body.insert(0, ast.parse('if sold == 0: continue').body[0])
    return ast.fix_missing_locations(fn)


def unknown_stop(original, episode, *, bars, session, cfg, carried, emit):
    """Only a missing bar with proved prior-source sizing provenance is unknown."""
    if any(bar.security_id == episode.security_id for bar in bars):
        return original(episode, bars=bars, session=session, cfg=cfg)
    need(not episode.exit_pending and Fraction(str(episode.current_shares)) > 0,
         'DIAGNOSTIC_UNKNOWN_STOP_ONLY_SURVIVING_HELD_EPISODE')
    need(carried is not None and type(carried['source_stale_raw_close']) in (int, float)
         and math.isfinite(carried['source_stale_raw_close']) and carried['source_stale_raw_close'] > 0
         and type(carried['source_print_session']) is str and carried['source_print_session'] < session,
         'DIAGNOSTIC_UNKNOWN_STOP_POSITIVE_DATED_PRIOR_SOURCE_MARK')
    before = material(deepcopy(episode))
    detached = deepcopy(episode)
    try:
        original(detached, bars=bars, session=session, cfg=cfg)
    except ValueError as error:
        need(str(error) == 'REFUSED_VOLATILITY_CAUSAL_AXIS', 'DIAGNOSTIC_UNKNOWN_STOP_EXACT_ORIGINAL_REFUSAL')
    else:
        raise ValueError('DIAGNOSTIC_UNKNOWN_STOP_ORIGINAL_DID_NOT_REFUSE')
    need(material(detached) == before and material(episode) == before,
         'DIAGNOSTIC_UNKNOWN_STOP_ENTIRE_EPISODE_FLOOR_AND_CURSOR_UNCHANGED')
    emit(before, carried)
    return False


def context_class(base, policy):
    need(isinstance(policy, DiscoveryPolicy), 'EXPLICIT_APPROVED_DIAGNOSTIC_POLICY')
    selected = policy.commitment()

    class ApprovedContext(base):
        def __init__(self, *args, **kwargs):
            saved = kwargs.get('saved') or {}
            super().__init__(*args, **kwargs)
            self.approx_carried = {}
            self.approx_boundary = saved.get('diagnostic_policy')
            if self.approx_boundary is not None:
                need(self.approx_boundary['sha256'] == selected['sha256'],
                     'DIAGNOSTIC_RESUME_SAME_APPROVED_POLICY')

        def __enter__(self):
            from full_system_core import hosted
            hosted()
            value = super().__enter__()
            try:
                from stock_strategy_shared.wealth_core import capital_risk
                raw = Path(capital_risk.__file__).read_bytes()
                need(hashlib.sha256(raw).hexdigest() == policy.native_risk_source_sha256,
                     'DIAGNOSTIC_EXACT_OWN_ORIGINAL_RISK_MODULE')
                need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == policy.implementation_sha256,
                     'DIAGNOSTIC_EXACT_APPROVED_POLICY_IMPLEMENTATION')
                if policy.arm == 'P09':
                    def plan(episodes, target, total):
                        quantities = [(slot, ep.current_shares) for slot, ep in episodes]
                        rows, proof = allocate_trim(quantities, target, exact=capital_risk.exact_float,
                            maximum_places=policy.maximum_share_decimal_places)
                        need(sum((Fraction(str(q)) for _, q in quantities), Fraction()) == total,
                             'DIAGNOSTIC_PLANNER_ORIGINAL_HOLDER_QUANTITY')
                        if proof['rounded']:
                            self.emit('DIAGNOSTIC_TRIM_ALLOCATION_ROUNDED', episodes[0][1].security_id,
                                bypass=True, policy_sha256=selected['sha256'], allocation=proof,
                                no_price_fee_or_holder_target_change=True)
                        by_slot = dict(episodes)
                        return [(slot, by_slot[slot], remain, sold) for slot, remain, sold in rows]
                    scope = dict(vars(capital_risk), diagnostic_plan=plan)
                    exec(compile(ast.Module(body=[trim_tree(raw)], type_ignores=[]),
                         '<owner-approved-discovery-p09-allocation>', 'exec'), scope)
                    self.patch(capital_risk, 'trim_decisions', scope['trim_decisions'])
                else:
                    original = capital_risk.volatility_stop
                    def stop(episode, *, bars, session, cfg):
                        if cfg.economic_profile != capital_risk.V_PROFILE:
                            return original(episode, bars=bars, session=session, cfg=cfg)
                        def emit(before, carried):
                            self.emit('DIAGNOSTIC_STOP_UNKNOWN_HOLDING_CARRIED', episode.security_id,
                                bypass=True, policy_sha256=selected['sha256'], prior_episode=before,
                                after_episode=material(episode), source_sizing_carry=carried,
                                original_refusal='REFUSED_VOLATILITY_CAUSAL_AXIS',
                                stop_outcome='UNKNOWN_DEFERRED', no_bar_fill_cash_or_writeoff_created=True)
                        return unknown_stop(original, episode, bars=bars, session=session, cfg=cfg,
                            carried=self.approx_carried.get(episode.security_id), emit=emit)
                    self.patch(capital_risk, 'volatility_stop', stop)
                return value
            except BaseException:
                self.restore()
                self.stream.close()
                raise

        def emit(self, kind, sid=None, *, bypass=False, **context):
            if kind == 'DIAGNOSTIC_SIZING_CARRY':
                self.approx_carried[sid] = deepcopy(context)
            return super().emit(kind, sid, bypass=bypass, **context)

        def advance(self, run, published):
            self.approx_carried = {}
            if self.approx_boundary is None:
                need(self.current is None, 'DIAGNOSTIC_POLICY_BOUNDARY_BEFORE_TRANSITION')
                self.current = (run, published)
                try:
                    self.emit('DIAGNOSTIC_POLICY_BOUND', policy=selected,
                        no_financial_state_or_input_change=True, no_performance_authority=True)
                    self.approx_boundary = dict(selected, first_session=published.session,
                        boundary_event_chain_sha256=self.chain)
                finally:
                    self.current = None
            return super().advance(run, published)

        def policy_commitment(self):
            return deepcopy(self.approx_boundary)

    return ApprovedContext
