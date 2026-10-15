"""Execute the emitted filesystem guard, including successful omissions."""
from contextlib import contextmanager
import os
from pathlib import Path
import shlex
import subprocess

import pytest

from sentinel import backup_runtime_authority as authority
from lab import BASE,SYSTEM_ID,Media,wal_name


def emitted_guard(tmp_path,monkeypatch):
    media=Media(tmp_path/'media')
    monkeypatch.setattr(authority,'BASE_ROOT',str(media.base))
    monkeypatch.setattr(authority,'WAL_ROOT',str(media.wal))
    queries=[]
    class Cursor:
        def execute(self,query):queries.append(query)
    class Connection:
        @contextmanager
        def cursor(self):yield Cursor()
    authority._require_no_aliases(Connection(),base=BASE,system_id=str(SYSTEM_ID),objects=(wal_name(3),))
    literal=queries[0].split(' TO PROGRAM ',1)[1]
    program=literal[1:-1].replace("''", "'")
    return media,shlex.split(program)[-1]


def execute(script,*,env=None):
    return subprocess.run(['sh','-ceu',script],input=wal_name(3)+'\n',
        text=True,capture_output=True,env=env,timeout=5)


def test_complete_required_files_pass_actual_guard(tmp_path,monkeypatch):
    _,script=emitted_guard(tmp_path,monkeypatch)
    result=execute(script)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('damage',['missing-wal','missing-sidecar','symlink','hardlink','directory'])
def test_missing_or_aliased_required_path_refuses(tmp_path,monkeypatch,damage):
    media,script=emitted_guard(tmp_path,monkeypatch)
    path=media.namespace/wal_name(3)
    if damage=='missing-sidecar':path=path.with_name(path.name+'.sha256')
    if damage=='hardlink':os.link(path,media.namespace/'retained-link')
    else:
        path.unlink()
        if damage=='symlink':path.symlink_to(media.namespace/wal_name(4))
        if damage=='directory':path.mkdir()
    result=execute(script)
    assert result.returncode in {44,45},result.stderr


def test_successful_find_omission_requires_positive_coverage(tmp_path,monkeypatch):
    _,script=emitted_guard(tmp_path,monkeypatch)
    commands=tmp_path/'bin';commands.mkdir()
    find=commands/'find'
    find.write_text('#!/bin/sh\n/usr/bin/find "$@" | head -n 1\n')
    find.chmod(0o755)
    env={**os.environ,'PATH':str(commands)+':'+os.environ['PATH']}
    assert execute(script,env=env).returncode==45
    weakened=script.replace('[ "$count" -eq 2 ] || exit 45','true')
    assert weakened!=script
    # The exact same omitted-path result passes if the coverage guard vanishes.
    assert execute(weakened,env=env).returncode==0


def test_hash_statements_are_bounded_without_dropping_objects():
    from types import SimpleNamespace
    groups=[]
    class Cursor:
        def execute(self,query,params):
            assert 'pg_read_binary_file' in query
            self.names=params[1]
            groups.append(self.names)
            assert params[2]==[16*1024*1024]*len(self.names)
        def fetchall(self):return [(name,'0'*64) for name in self.names]
    @contextmanager
    def cursor():yield Cursor()
    names=tuple(wal_name(n) for n in range(9))
    result=authority._hash_objects(SimpleNamespace(cursor=cursor),root='/bounded',objects=names,
        sizes={name:16*1024*1024 for name in names})
    assert [len(group) for group in groups]==[4,4,1]
    assert tuple(result)==names
