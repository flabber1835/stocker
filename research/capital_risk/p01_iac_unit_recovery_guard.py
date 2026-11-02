"""Source-bound adapter.Buffer context hook; frozen unit economics unchanged."""
import ast
from pathlib import Path

from p01_iac_unit_contract import need, sha
from p01_iac_unit_guard import UnitGuard as FrozenUnitGuard
from p01_factual_batch_guard import ActionGuard

BACKTEST = 'research/pooled_vacancy_funding/backtest.py'
ADAPTER = 'research/pooled_input_support/adapter.py'
BACKTEST_SHA = 'b6d0eeec392990518e2ba5e210737050a5d8a310c2c2aeac80db40952e2185fc'
ADAPTER_SHA = '4fcb1326b8b9e713837257613330abd33927e940106e1473654958f085c1fc08'
FROZEN_GUARD_SHA = 'f0d96a076d866969c9226a4f02ca263472ee8714b76dd094ccf0640670ee5fbd'


def interface(backtest_source, adapter_source):
    """Inspect actual canonical source; execute no canonical function."""
    need(sha(backtest_source) == BACKTEST_SHA and sha(adapter_source) == ADAPTER_SHA,
         'RECOVERY_EXACT516_BACKTEST_AND_ADAPTER_PREIMAGES')
    tree = ast.parse(backtest_source)
    imports = [n for n in tree.body if isinstance(n, ast.ImportFrom)
               and n.module == 'research.pooled_input_support']
    need(len(imports) == 1 and [(n.name, n.asname) for n in imports[0].names]
         == [('adapter', None), ('bundle', None), ('inputs', None)],
         'RECOVERY_EXACT_BACKTEST_ADAPTER_MODULE_IMPORT')
    run, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_backtest']
    constructions = [n for n in ast.walk(run) if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'buffer' for t in n.targets)]
    need(len(constructions) == 1 and isinstance(constructions[0].value, ast.Call)
         and ast.unparse(constructions[0].value) == 'adapter.Buffer()',
         'RECOVERY_EXACT_BUFFER_CONSTRUCTION_IN_RUN_BACKTEST')
    need(not any(isinstance(n, (ast.Import, ast.ImportFrom)) and
         any(a.asname == 'Buffer' or a.asname is None and a.name == 'Buffer' for a in n.names)
         for n in tree.body), 'RECOVERY_NO_MODULE_GLOBAL_BUFFER_IMPORT')
    adapter = ast.parse(adapter_source)
    cls, = [n for n in adapter.body if isinstance(n, ast.ClassDef) and n.name == 'Buffer']
    prepare, = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'prepare']
    return dict(schema='research.p01-iac-unit-recovery-buffer-interface/1',
        source_files={BACKTEST:BACKTEST_SHA, ADAPTER:ADAPTER_SHA},
        backtest_adapter_module_import=True, run_backtest_uses_adapter_buffer=True,
        run_backtest_function_sha256=sha(ast.get_source_segment(backtest_source.decode(), run).encode()),
        buffer_prepare_function_sha256=sha(ast.get_source_segment(adapter_source.decode(), prepare).encode()),
        financial_source_changed=False)


def resolve_buffer(backtest, adapter, contract):
    proof = interface(Path(backtest.__file__).read_bytes(), Path(adapter.__file__).read_bytes())
    need(contract['source_files'][ADAPTER] == ADAPTER_SHA,
         'RECOVERY_SAME_ACTUAL516_SOURCE_CONTRACT')
    need(backtest.adapter is adapter and backtest.adapter.Buffer is adapter.Buffer
         and 'Buffer' not in vars(backtest), 'RECOVERY_ACTUAL_ADAPTER_MODULE_AND_CLASS_IDENTITY')
    need(adapter.Buffer.prepare.__module__ == adapter.__name__
         and adapter.Buffer.prepare.__qualname__ == 'Buffer.prepare',
         'RECOVERY_ORIGINAL_PREPARE_NOT_ALREADY_HOOKED')
    return adapter.Buffer, proof


class UnitGuard(FrozenUnitGuard):
    """Only the context lifecycle differs from the published failed driver."""
    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import backtest
        from research.pooled_input_support import adapter
        need(sha(Path(__file__).with_name('p01_iac_unit_guard.py').read_bytes()) == FROZEN_GUARD_SHA,
             'RECOVERY_FROZEN_UNIT_GUARD_BYTES')
        need(not getattr(self, '_recovery_active', False), 'RECOVERY_CONTEXT_NOT_REENTERED')
        buffer_class, proof = resolve_buffer(backtest, adapter, self.contract)
        original_prepare = buffer_class.prepare
        self.buffer_class = buffer_class
        self.original_prepare = original_prepare
        self.recovery_interface_proof = proof
        ActionGuard.__enter__(self)
        try:
            need(self.backtest is backtest and buffer_class.prepare is original_prepare,
                 'RECOVERY_CLASS_UNCHANGED_DURING_BASE_CONTEXT_SETUP')
            self._recovery_prepare = lambda buffer, *a, **k: self.prepare(buffer, *a, **k)
            buffer_class.prepare = self._recovery_prepare
            self._recovery_active = True
            return self
        except BaseException:
            buffer_class.prepare = original_prepare
            ActionGuard.__exit__(self, None, None, None)
            raise

    def __exit__(self, *args):
        try:
            self.buffer_class.prepare = self.original_prepare
        finally:
            self._recovery_active = False
            ActionGuard.__exit__(self, *args)
