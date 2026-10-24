"""Frozen legacy admission condition from the independently pinned Git witness.

The legacy addition adapters below reproduce original per-release atomic versus
individual checks; the current registry is never called by this oracle.
"""
from types import SimpleNamespace
import hashlib
from pathlib import Path


def _adapters(profiles):
    from sentinel.transition_registry_specs import PROFILES
    specs = {spec.key: spec for spec in PROFILES}
    def allowed(key, actual):
        expected = dict(profiles[key].get('additions', {}))
        if key in {'opening_latency', 'protected_cohort'}:
            expected[specs[key].checker + '.py'] = specs[key].checker_sha256
        if key in {'opening_latency', 'protected_cohort'}:
            return set(expected) if all(actual.get(name) == sha for name, sha in expected.items()) else set()
        checker = specs[key].checker + '.py'
        if key == 'idle_leader':
            return {checker} if actual.get(checker) == specs[key].checker_sha256 else set()
        result = {name for name, sha in expected.items() if actual.get(name) == sha}
        if (key in {'autonomy', 'native_read', 'clock_sampling'}
                and actual.get(checker) == specs[key].checker_sha256):
            result.add(checker)
        return result
    return {key: SimpleNamespace(
        additions_allowed=lambda actual, key=key: allowed(key, actual),
        ADDITIONS=frozenset(value.get('additions', {})), SCOPE=frozenset(value['files']))
        for key, value in profiles.items()}


def legacy_closure_allowed(profiles, previous_files, actual, ADDITIONS):
    adapters = _adapters(profiles)
    legacy_economic_profile = profiles['legacy_economic']
    economic_profile = profiles['economic']
    execution_records = profiles['execution']
    readiness_records = profiles['readiness']
    renewal_records = profiles['renewal']
    liveness_records = profiles['liveness']
    operational_profile = profiles['operational']
    operational_upgrade = adapters['operational']
    callback_profile = profiles['callback']
    callback_upgrade = adapters['callback']
    startup_profile = profiles['startup']
    startup_upgrade = adapters['startup']
    recovery_profile = profiles['recovery']
    recovery_upgrade = adapters['recovery']
    ui_profile = profiles['ui']
    ui_upgrade = adapters['ui']
    monitor_profile = profiles['monitor']
    monitor_upgrade = adapters['monitor']
    open_time_profile = profiles['open_time']
    open_time_upgrade = adapters['open_time']
    close_cycle_profile = profiles['close_cycle']
    close_cycle_upgrade = adapters['close_cycle']
    autonomy_profile = profiles['autonomy']
    autonomy_upgrade = adapters['autonomy']
    native_read_profile = profiles['native_read']
    native_read_upgrade = adapters['native_read']
    clock_sampling_profile = profiles['clock_sampling']
    clock_sampling_upgrade = adapters['clock_sampling']
    idle_leader_profile = profiles['idle_leader']
    idle_leader_upgrade = adapters['idle_leader']
    opening_latency_profile = profiles['opening_latency']
    opening_latency_upgrade = adapters['opening_latency']
    protected_cohort_profile = profiles['protected_cohort']
    protected_cohort_upgrade = adapters['protected_cohort']
    profiles = tuple(profiles.values())
    def source_allowed(name, previous, actual, records=profiles):
        for value in records:
            record = value['files'].get(name)
            if record is not None and previous in record['before'] and actual == record['after']:
                return True
        return False

    operational_additions = operational_upgrade.additions_allowed(actual)
    recovery_additions = recovery_upgrade.additions_allowed(actual)
    ui_additions = ui_upgrade.additions_allowed(actual)
    monitor_additions = monitor_upgrade.additions_allowed(actual)
    open_time_additions = open_time_upgrade.additions_allowed(actual)
    close_cycle_additions = close_cycle_upgrade.additions_allowed(actual)
    autonomy_additions = autonomy_upgrade.additions_allowed(actual)
    native_read_additions = native_read_upgrade.additions_allowed(actual)
    clock_sampling_additions = clock_sampling_upgrade.additions_allowed(actual)
    idle_leader_additions = idle_leader_upgrade.additions_allowed(actual)
    opening_latency_additions = opening_latency_upgrade.additions_allowed(actual)
    protected_cohort_additions = protected_cohort_upgrade.additions_allowed(actual)
    # Keep the predecessor's atomic addition check intact. Normalize only
    # members with an exact authenticated successor, leaving its own checker
    # and every other member subject to the predecessor's original check.
    opening_predecessor = dict(actual)
    for name, previous in opening_latency_profile['additions'].items():
        if source_allowed(name, previous, actual.get(name), (protected_cohort_profile,)):
            opening_predecessor[name] = previous
    opening_latency_additions.update(
        opening_latency_upgrade.additions_allowed(opening_predecessor))
    # An earlier pinned addition can later receive only its exact reviewed
    # transition; an unpinned neighboring edit still fails the closure gate.
    for previous_profile, allowed in ((operational_profile, operational_additions),
                                     (recovery_profile, recovery_additions),
                                     (ui_profile, ui_additions),
                                     (monitor_profile, monitor_additions),
                                     (open_time_profile, open_time_additions),
                                     (close_cycle_profile, close_cycle_additions),
                                     (autonomy_profile, autonomy_additions),
                                     (clock_sampling_profile, clock_sampling_additions),
                                     (opening_latency_profile, opening_latency_additions)):
        allowed.update(name for name, previous in previous_profile['additions'].items()
                       if (actual.get(name) == previous
                           or source_allowed(name, previous, actual.get(name), profiles[-9:])))
    if (set(previous_files) - set(actual)
            or native_read_upgrade.ADDITIONS - set(actual)
            or clock_sampling_upgrade.ADDITIONS - set(actual)
            or idle_leader_upgrade.ADDITIONS - set(actual)
            or opening_latency_upgrade.ADDITIONS - set(actual)
            or protected_cohort_upgrade.ADDITIONS - set(actual)
            or set(actual) - set(previous_files) - ADDITIONS - operational_additions - recovery_additions - ui_additions - monitor_additions - open_time_additions - close_cycle_additions - autonomy_additions - native_read_additions - clock_sampling_additions - idle_leader_additions - opening_latency_additions - protected_cohort_additions
            or (set(actual) & set(operational_profile['additions'])) - operational_additions
            or (set(actual) & set(recovery_profile['additions'])) - recovery_additions
            or (set(actual) & set(ui_profile['additions'])) - ui_additions
            or (set(actual) & set(monitor_profile['additions'])) - monitor_additions
            or (set(actual) & set(open_time_profile['additions'])) - open_time_additions
            or (set(actual) & set(close_cycle_profile['additions'])) - close_cycle_additions
            or (set(actual) & set(autonomy_profile['additions'])) - autonomy_additions
            or (set(actual) & set(native_read_profile['additions'])) - native_read_additions
            or (set(actual) & set(clock_sampling_profile['additions'])) - clock_sampling_additions
            or (set(actual) & set(idle_leader_profile['additions'])) - idle_leader_additions
            or (set(actual) & set(opening_latency_profile['additions'])) - opening_latency_additions
            or (set(actual) & set(protected_cohort_profile['additions'])) - protected_cohort_additions
            or any(name in actual and actual[name] != record['after']
                   and not source_allowed(name, record['after'], actual[name], (clock_sampling_profile, idle_leader_profile, opening_latency_profile, protected_cohort_profile))
                   for name, record in native_read_profile['files'].items())
            or any(name in actual and actual[name] != record['after']
                   and not source_allowed(name, record['after'], actual[name], (idle_leader_profile, opening_latency_profile, protected_cohort_profile))
                   for name, record in clock_sampling_profile['files'].items())
            or any(name in actual and actual[name] != record['after']
                   and not source_allowed(name, record['after'], actual[name], (opening_latency_profile, protected_cohort_profile))
                   for name, record in idle_leader_profile['files'].items())
            or any(name in actual and actual[name] != record['after']
                   and not source_allowed(name, record['after'], actual[name], (protected_cohort_profile,))
                   for name, record in opening_latency_profile['files'].items())
            or any(name in actual and actual[name] != record['after']
                   for name, record in protected_cohort_profile['files'].items())):
        return False
    return True
