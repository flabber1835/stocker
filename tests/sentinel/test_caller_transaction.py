"""Caller-owned ports cannot commit, roll back or close an enclosing unit."""
import ast
import inspect

import pytest

from sentinel.transaction_contract import borrow
from sentinel.feed import generation_admission, normalized_layout


def test_borrowed_transaction_only_forwards_query_operations():
    class Connection:
        def execute(self,*args): return ('execute',args)
        def cursor(self,*args,**kwargs): return ('cursor',args,kwargs)
        def commit(self): pytest.fail('caller transaction committed')
        def rollback(self): pytest.fail('caller transaction rolled back')
    conn = Connection()
    port = borrow(conn)
    assert port.execute('SELECT %s',(7,)) == ('execute',('SELECT %s',(7,)))
    assert port.cursor(name='stream') == ('cursor',(),{'name':'stream'})
    assert borrow(port) is port
    for method in ('commit','rollback','close'):
        with pytest.raises(AttributeError):
            getattr(port,method)


@pytest.mark.parametrize('module',[normalized_layout,generation_admission])
def test_caller_owned_storage_modules_have_no_transaction_ending_operation(module):
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
            assert node.func.attr not in {'commit','rollback','close'}
