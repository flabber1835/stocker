"""Fresh parent/fork proofs for immutable helper bootstrap and child safety."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux parent-death contract')

PROBE = r'''
import collections,json,os,signal,sys,types
from pathlib import Path

COUNTS=None
INHERITED=None

def after_fork():
 global COUNTS,INHERITED
 COUNTS=collections.Counter()
 INHERITED='ctypes' in sys.modules
 def audit(event,args):
  if event=='open' and args and isinstance(args[0],str):
   path=args[0].replace('\\','/')
   if '/ctypes/' in path or path.rsplit('/',1)[-1].startswith('_ctypes.'):
    COUNTS['ctypes_open_attempts']+=1
 sys.addaudithook(audit)

def child_state():
 import ctypes
 armed=ctypes.c_int()
 libc=ctypes.CDLL(None,use_errno=True)
 if libc.prctl(2,ctypes.byref(armed),0,0,0)!=0:
  raise OSError(ctypes.get_errno(),'PR_GET_PDEATHSIG failed')
 return {'inherited_ctypes':INHERITED,'ctypes_open_attempts':COUNTS['ctypes_open_attempts'] if COUNTS is not None else None,
         'parent_death_signal':armed.value,'parent_pid':os.getppid()}

def main():
 mode,filename=sys.argv[1:]
 before='ctypes' in sys.modules
 if mode=='mutant':
  raw=Path(filename).read_text()
  assert raw.count('\nimport ctypes\n')==1
  raw=raw.replace('\nimport ctypes\n','\n',1)
  assert raw.count('    libc = ctypes.CDLL(None, use_errno=True)')==1
  raw=raw.replace('    libc = ctypes.CDLL(None, use_errno=True)',
                  '    import ctypes\n    libc = ctypes.CDLL(None, use_errno=True)',1)
  module=types.ModuleType('supervisor_io_bootstrap_mutant')
  module.__file__=filename
  sys.modules[module.__name__]=module
  exec(compile(raw,filename,'exec'),module.__dict__)
 else:
  from sentinel import supervisor_io as module
 loaded='ctypes' in sys.modules
 os.register_at_fork(after_in_child=after_fork)
 method='spawn' if mode=='spawn' else 'fork'
 count=1 if mode=='spawn' else 3
 values=[module.run(child_state,start_method=method,timeout=3) for _ in range(count)]
 print(json.dumps({'ctypes_before_import':before,'parent_ctypes_loaded':loaded,
                   'parent_pid':os.getpid(),'values':values}),flush=True)

if __name__=='__main__':
 main()
'''


def fresh_probe(tmp_path, mode):
    script = tmp_path / 'helper_bootstrap_probe.py'
    script.write_text(PROBE)
    import importlib.util
    source = Path(importlib.util.find_spec('sentinel.supervisor_io').origin)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
    result = subprocess.run([sys.executable, '-B', str(script), mode, str(source)],
                            capture_output=True, text=True, env=env, timeout=12)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['ctypes_before_import'] is False, 'fresh-process fixture preloaded ctypes'
    return value


def assert_no_repeated_ctypes_open(value):
    for child in value['values']:
        assert child['ctypes_open_attempts'] == 0, 'ctypes file reopened in helper'
        assert child['inherited_ctypes'] is True


def assert_child_signal(value):
    import signal
    for child in value['values']:
        assert child['parent_death_signal'] == signal.SIGKILL
        assert child['parent_pid'] == value['parent_pid']


def test_fork_helpers_inherit_ctypes_without_reopening_its_files(tmp_path):
    value = fresh_probe(tmp_path, 'fork')
    assert value['parent_ctypes_loaded'] is True
    assert len(value['values']) == 3
    assert_no_repeated_ctypes_open(value)
    assert_child_signal(value)


def test_removed_parent_preimport_restores_repeated_child_file_opens(tmp_path):
    value = fresh_probe(tmp_path, 'mutant')
    assert value['parent_ctypes_loaded'] is False
    assert len(value['values']) == 3
    assert all(child['ctypes_open_attempts'] > 0 for child in value['values'])
    assert_child_signal(value)
    with pytest.raises(AssertionError, match='ctypes file reopened in helper'):
        assert_no_repeated_ctypes_open(value)


def test_spawn_helper_still_arms_its_own_sigkill(tmp_path):
    value = fresh_probe(tmp_path, 'spawn')
    assert value['parent_ctypes_loaded'] is True
    assert_child_signal(value)
