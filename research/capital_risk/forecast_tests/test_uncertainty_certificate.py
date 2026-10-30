"""Synthetic journal commitment and exact-prefix continuation tests only."""
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from system_campaign_uncertainty_context import SensorCertificate, SCHEMA, WATCH_SCHEMA, digest, encoded
from system_campaign_uncertainty_review import seed


def synthetic(tmp_path):
    class Journal:
        def __init__(self): self.rows = []
        def append(self, name, record): self.rows.append((name, record))
    c = SensorCertificate(tmp_path, None, None, {})
    c.original_append = Journal.append
    c.stream = (tmp_path / 'uncertainty-certificate.jsonl').open('xb')
    c.pending = dict(schema=SCHEMA, session='2019-10-22', input_sha256='a' * 64,
                     prior_state_sha256='b' * 64, next_state_sha256='c' * 64)
    record = dict(session='2019-10-22', input_sha256='a' * 64, state_sha256='c' * 64)
    return c, Journal(), record


def finish(root, journal, cp_cursor='2019-10-22'):
    book = root / 'book';book.mkdir()
    commitments = {}
    for name in ('formation', 'daily', 'monthly', 'watch'):
        raw = b''.join(encoded(row) + b'\n' for kind, row in journal.rows if kind == name)
        (book / (name + '.jsonl')).write_bytes(raw)
        commitments[name] = dict(bytes=len(raw), prefix_sha256=sha256(raw).hexdigest())
    return dict(journals=commitments, source_cursor=cp_cursor)


def test_certificate_is_fsynced_and_watch_committed_before_financial_append(tmp_path):
    c, j, record = synthetic(tmp_path)
    c.append(j, 'daily', record)
    c.stream.close()
    assert [kind for kind, _ in j.rows] == ['watch', 'daily']
    assert j.rows[0][1]['schema'] == WATCH_SCHEMA and c.rows == 1 and c.pending is None
    cp = finish(tmp_path, j)
    rows = seed(tmp_path, cp)
    assert len(rows) == 1 and rows[0]['next_state_sha256'] == record['state_sha256']


def test_wrong_financial_state_refuses_without_certificate_or_watch_commit(tmp_path):
    c, j, record = synthetic(tmp_path)
    record['state_sha256'] = 'd' * 64
    with pytest.raises(ValueError, match='EXACT_FINANCIAL_ROW'):
        c.append(j, 'daily', record)
    c.stream.close()
    assert not j.rows and (tmp_path / 'uncertainty-certificate.jsonl').read_bytes() == b''


def test_missing_nonempty_certificate_never_seeds_empty(tmp_path):
    j = SimpleNamespace(rows=[('daily', dict(session='2019-10-22', state_sha256='c' * 64))])
    cp = finish(tmp_path, j)
    with pytest.raises(ValueError, match='MISSING_COMMITTED_CERTIFICATE'):
        seed(tmp_path, cp)


def test_no_rollback_to_future_certificate_row(tmp_path):
    c, j, record = synthetic(tmp_path)
    c.append(j, 'daily', record);c.stream.close()
    cp = finish(tmp_path, j)
    rows = seed(tmp_path, cp)
    row = {**rows[0], 'session': '2019-10-23'}
    with (tmp_path / 'uncertainty-certificate.jsonl').open('ab') as stream:
        stream.write(encoded(row) + b'\n')
    assert seed(tmp_path, cp) == rows
    # The future tail is not admitted, deleted or rewritten by prefix selection.
    assert len((tmp_path / 'uncertainty-certificate.jsonl').read_bytes().splitlines()) == 2


def test_actual_watch_binding_omission_falsifier(tmp_path):
    import inspect, textwrap
    from system_campaign_uncertainty_review import seed as original
    c, j, record = synthetic(tmp_path)
    c.append(j, 'daily', record);c.stream.close()
    j.rows[0][1]['certificate_chain_sha256'] = 'f' * 64
    cp = finish(tmp_path, j)
    with pytest.raises(ValueError, match='WATCH_AND_FINANCIAL'):
        seed(tmp_path, cp)
    raw = inspect.getsource(original)
    broken = raw.replace("and row['chain_sha256'] == watch['certificate_chain_sha256']", 'and True')
    assert broken != raw
    namespace = {}
    exec(textwrap.dedent(broken), original.__globals__, namespace)
    assert len(namespace['seed'](tmp_path, cp)) == 1


def test_actual_context_keeps_journal_instance_binding_and_restores_hooks(monkeypatch, tmp_path):
    import sys
    from types import ModuleType
    import system_campaign_uncertainty_context as module
    names = ('sentinel', 'sentinel.controller', 'research', 'research.pooled_vacancy_funding')
    packages = {n: ModuleType(n) for n in names}
    for name, value in packages.items():
        value.__path__ = []
        monkeypatch.setitem(sys.modules, name, value)
    def unchanged(*args, **kwargs): return None
    terminal = SimpleNamespace(values=unchanged)
    witness = SimpleNamespace(witness=unchanged)
    recovery = SimpleNamespace(recover=unchanged)
    runtime = SimpleNamespace(advance=unchanged)
    backtest = SimpleNamespace(relevant=unchanged)
    class Journal:
        def __init__(self): self.rows = []
        def append(self, name, record): self.rows.append((name, record))
    append = Journal.append
    controller = packages['sentinel.controller']
    controller.terminal_returns, controller.median5, controller.champion_config = terminal, witness, recovery
    pooled = packages['research.pooled_vacancy_funding']
    pooled.runtime, pooled.backtest, pooled.journal = runtime, backtest, SimpleNamespace(Journal=Journal)
    monkeypatch.setattr(module, 'hosted', lambda: None)
    # All stand-ins are synthetic. No canonical or historical module is loaded.
    with SensorCertificate(tmp_path, None, None, {}) as context:
        context.pending = dict(schema=SCHEMA, session='2019-10-22', input_sha256='a' * 64,
                               prior_state_sha256='b' * 64, next_state_sha256='c' * 64)
        j = Journal()
        j.append('daily', dict(session='2019-10-22', input_sha256='a' * 64, state_sha256='c' * 64))
        assert [kind for kind, _ in j.rows] == ['watch', 'daily']
    assert Journal.append is append and terminal.values is unchanged and runtime.advance is unchanged
    assert recovery.recover is unchanged and witness.witness is unchanged and backtest.relevant is unchanged


@pytest.mark.parametrize('mutation', ['none','bytes','source','duplicate'])
def test_retained_model_contract_binds_exact_code_and_physical_archive(monkeypatch,tmp_path,mutation):
    import system_campaign_uncertainty_facts as facts
    from system_campaign_uncertainty_review import validate_input_commitment
    from forecast_tests.test_uncertainty_input import document
    value=document();raw=encoded(value)+b'\n';digest=sha256(raw).hexdigest()
    folder=tmp_path/'book/repairs';folder.mkdir(parents=True)
    path=folder/(digest+'.json');path.write_bytes(raw)
    descriptor=dict(filename=path.name,sha256=digest,resume_session='2019-09-30',predecessor_checkpoint_sha256='a'*64)
    cp=dict(repairs=[descriptor]);expected=value['source_evidence']
    if mutation=='bytes':path.write_bytes(raw+b' ')
    if mutation=='source':expected=[]
    if mutation=='duplicate':cp['repairs'].append(descriptor)
    monkeypatch.setattr(facts,'evidence',lambda root:expected)
    if mutation=='none':assert validate_input_commitment(tmp_path,cp)==digest
    else:
        with pytest.raises(ValueError):validate_input_commitment(tmp_path,cp)
