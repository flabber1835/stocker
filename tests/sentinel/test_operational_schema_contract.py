"""An operational extension cannot hide unrelated or invalid catalog changes."""
from types import SimpleNamespace

import pytest

from sentinel import operational_schema as op


def catalog():
    return ({'sentinel_commands': ('r',), 'extension_table': ('r',)},
            {'sentinel_commands': {'state': ('text',)}, 'extension_table': {}},
            {'sentinel_commands': [('original',)], 'extension_table': []},
            {'sentinel_commands': {'original': ()}, 'extension_table': {}},
            {'sentinel_commands': {'known_extension': ('reviewed',), 'unknown': ('bad',)},
             'other_table': {'known_extension': ('unrelated',)}, 'extension_table': {}})


@pytest.fixture
def component(monkeypatch):
    value = SimpleNamespace(__name__='test.extension', extension_tables={'extension_table'},
                            extension_triggers={('sentinel_commands', 'known_extension')},
                            require_schema=lambda conn, **kw: True)
    monkeypatch.setattr(op, 'components', lambda: (value,))
    monkeypatch.setattr(op, 'installation', lambda conn, **kw: None)
    return value


def test_only_exact_validated_component_objects_leave_legacy_comparison(component):
    original = catalog()
    actual = op.legacy_catalog(object(), original)
    assert 'extension_table' not in actual[0]
    assert actual[1]['sentinel_commands'] == original[1]['sentinel_commands']
    assert actual[4]['sentinel_commands'] == {'unknown': ('bad',)}
    assert actual[4]['other_table'] == {'known_extension': ('unrelated',)}
    assert 'extension_table' in original[0]
    assert 'known_extension' in original[4]['sentinel_commands']


@pytest.mark.parametrize('failure', ['false', 'exception'])
def test_invalid_component_is_never_hidden(component, failure):
    def refuse(*args, **kwargs):
        if failure == 'exception':
            raise op.OperationalSchemaRefused('changed trigger')
        return False
    component.require_schema = refuse
    with pytest.raises(op.OperationalSchemaRefused):
        op.legacy_catalog(object(), catalog())


def test_installed_marker_requires_even_a_missing_component(component, monkeypatch):
    monkeypatch.setattr(op, 'installation', lambda conn, **kw: {'installed': True})
    component.require_schema = lambda *args, **kwargs: False
    with pytest.raises(op.OperationalSchemaRefused, match='COMPONENT_ABSENT'):
        op.legacy_catalog(object(), (
            {'sentinel_processed_sessions': ('r', 'p', False, False, False)},
            {'sentinel_processed_sessions': {
                'cursor_name': ('text', True), 'session': ('date', True),
                'state': ('jsonb', False)}}, {}, {}, {}))


def test_pure_predecessor_catalog_is_unchanged(component):
    value = ({'sentinel_commands': ('r',)}, {}, {}, {}, {})
    assert op.legacy_catalog(object(), value) is value


def test_legacy_projection_cannot_strip_a_same_named_foreign_trigger(component):
    actual = op.legacy_catalog(object(), catalog())
    assert actual[4]['other_table']['known_extension'] == ('unrelated',)


def test_absence_guard_has_a_falsifier(component, monkeypatch):
    original = op._require
    monkeypatch.setattr(op, '_require', lambda *args: None)
    with pytest.raises(pytest.fail.Exception):
        test_invalid_component_is_never_hidden(component, 'false')
    monkeypatch.setattr(op, '_require', original)
