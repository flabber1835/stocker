"""Narrow in-memory mutations of current registry guards for legacy cases."""
from sentinel import transition_registry as registry


def remove_required_addition(monkeypatch, key):
    # Separate the required-presence backstop from an atomic group's own test.
    original = registry.Transitions.additions_allowed
    def present_members(self, actual):
        result = original(self, actual)
        result[key] = set(self.profiles[key]['additions']) & set(actual)
        return result
    monkeypatch.setattr(registry.Transitions, 'additions_allowed', present_members)
    monkeypatch.setattr(registry, 'REQUIRED_ADDITIONS', tuple(
        candidate for candidate in registry.REQUIRED_ADDITIONS if candidate != key))


def isolate_current_pin(monkeypatch, key):
    keys = tuple(registry.FILE_SUCCESSORS)
    selected = keys.index(key)
    monkeypatch.setattr(registry, 'FILE_SUCCESSORS', {
        candidate: value for candidate, value in registry.FILE_SUCCESSORS.items()
        if candidate not in keys[selected + 1:]})


def remove_current_pin(monkeypatch, key):
    monkeypatch.setattr(registry, 'FILE_SUCCESSORS', {
        candidate: value for candidate, value in registry.FILE_SUCCESSORS.items() if candidate != key})


def remove_admission_scope(monkeypatch):
    monkeypatch.setattr(registry, 'NONADMINISTRATIVE_SCOPES', ())
