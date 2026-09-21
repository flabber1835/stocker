"""Independent mechanism checks for the fixed research parameter alternatives."""
from copy import deepcopy
import json

import pytest

from research.impedance.parameters import (
    PRESETS, ProbeController, assert_baseline, production_constants,
)


def row(**changes):
    observation = dict(shadow_drawdown=0., shadow_r5=.01, shadow_r10=.02,
        shadow_r20=.03, shadow_r40=.04, damaged_breadth=.2, green_breadth=.6,
        damaged_breadth_delta5=0., spy_r20=.02, spy_vol_ratio=0., stops20=0,
        shadow_nav=100.)
    observation.update(changes)
    return dict(observation=observation, leadership=dict(recent_r20=.03, recent_r40=.04))


def test_fast_halving_changes_only_the_intermediate_acceleration_case():
    point = row(shadow_drawdown=-.12, shadow_r5=-.06, shadow_r10=-.09,
        damaged_breadth=.9, green_breadth=.1, damaged_breadth_delta5=.2,
        spy_vol_ratio=.05, spy_r20=-.02, shadow_nav=88.)
    assert ProbeController('current').step(point)['native'] == 1.
    assert ProbeController('fast_sensitive').step(point)['native'] == 0.
    point['observation']['damaged_breadth_delta5'] = 0.
    assert ProbeController('fast_sensitive').step(point)['native'] == 1.


def test_slow_halving_advances_qualifying_loss_but_needs_a_base_anchor():
    probes = {n: ProbeController(n) for n in ('current', 'slow_earlier')}
    entries = {}
    for day in range(35):
        point = row(shadow_drawdown=-.16 if day == 0 else -.19,
            shadow_nav=84. if day == 0 else 81., shadow_r20=-.1, shadow_r40=-.04,
            damaged_breadth=.9, green_breadth=.1)
        for name, probe in probes.items():
            if probe.step(point)['native'] == 0.:
                entries.setdefault(name, day)
    assert entries == {'slow_earlier': 14, 'current': 29}


@pytest.mark.parametrize('name', PRESETS)
def test_persistent_flat_damage_still_cannot_trigger_native(name):
    probe = ProbeController(name)
    # Base stress exists, but there is neither acceleration nor further loss
    # from its anchor. Strong leadership also prevents the LD ceiling.
    point = row(shadow_drawdown=-.2, shadow_nav=80., shadow_r5=0., shadow_r10=0.,
        shadow_r20=0., shadow_r40=-.2, damaged_breadth=1., green_breadth=0.)
    for _ in range(60):
        result = probe.step(point)
        assert result['native'] == result['target'] == 1.


def test_four_vs_eight_positive_closes_releases_existing_recovery_episode():
    for name, required in (('current', 8), ('recovery_faster', 4)):
        candidate = ProbeController(name).candidate
        candidate.step(0., 1., -.2, -.1, -.1, -.1, -.1)
        for day in range(1, 9):
            target, _ = candidate.step(1., 1., -.1, .02, .02, .02, .01)
            assert target == (1. if day >= required else 0.)


def test_variant_namespace_cannot_change_production_or_other_variants():
    original = production_constants()
    current, modified = ProbeController('current'), ProbeController('combined')
    modified.Native.step.__globals__['FAST']['ddam5'] = 999.
    assert current.Native.step.__globals__['FAST']['ddam5'] == .3
    assert production_constants() == original


def test_research_snapshot_refuses_cross_parameter_identity():
    source, other = ProbeController('current'), ProbeController('combined')
    with pytest.raises(ValueError, match='identity mismatch'):
        other.restore(source.snapshot())


@pytest.mark.parametrize('name', PRESETS)
def test_research_snapshot_continuation(name):
    running = ProbeController(name)
    for day in range(12):
        point = row(shadow_drawdown=-.12, shadow_r5=-.06,
            damaged_breadth=.9, green_breadth=.1, damaged_breadth_delta5=.2,
            spy_vol_ratio=.05, spy_r20=-.02, shadow_nav=88.) if day < 3 else row()
        restored = ProbeController(name)
        restored.restore(json.loads(json.dumps(running.snapshot())))
        assert restored.step(point) == running.step(point)
        assert restored.snapshot() == running.snapshot()


def test_parity_guard_detects_target_divergence():
    probe = ProbeController('current')
    point = row()
    result = probe.step(point)
    point.update(core_multiplier=1., native_multiplier=1., recovery_reason='NORMAL',
                 native_evidence={'native_snapshot': probe.native.snapshot()})
    assert_baseline(point, result, probe)
    broken = deepcopy(result)
    broken['target'] = .55
    with pytest.raises(AssertionError, match='production target parity'):
        assert_baseline(point, broken, probe)
