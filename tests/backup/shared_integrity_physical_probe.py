"""Actual PostgreSQL file/lock protocol, only in the private qualification PG.

Calls the production archive-validation boundary. This is not a physical
restore drill or a claim that this synthetic cluster has a qualified backup.
"""
import json
import os
import shlex
import sys

import psycopg

from sentinel import backup_integrity_reuse as reuse, backup_runtime_authority as authority


def main():
    dsn,scenario=sys.argv[1:]
    assert os.environ.get('SENTINEL_PRIVATE_INTEGRITY_QUALIFICATION')=='1'
    assert reuse.selected()
    with psycopg.connect(dsn,connect_timeout=3) as conn:
        system_id=conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]
        root=f'{authority.WAL_ROOT}/cluster-{system_id}'
        names=tuple(f'0000000100000000{number:08X}' for number in (2,3))
        arguments=dict(operation='synthetic native archive validation',system_id=system_id,
            base='base-20261109T000000Z',wal_root=root,wal_objects=names,
            history_object=None,segment_size=16*1024*1024,start=names[0],end=names[-1])
        if scenario=='prime':
            script=f'mkdir -p {shlex.quote(root)} {authority.BASE_ROOT}/base-20261109T000000Z; '
            for name in names:
                path=f'{root}/{name}'
                script+=f'truncate -s 16777216 {shlex.quote(path)}; '
                script+=f"sha256sum {shlex.quote(path)} | cut -d' ' -f1 | sed 's/^/sha256=/' > {shlex.quote(path+'.sha256')}; "
            program=('sh -ceu '+shlex.quote(script)).replace("'","''")
            conn.execute(f"COPY (SELECT 'synthetic') TO PROGRAM '{program}'")
        if scenario=='busy':
            with psycopg.connect(dsn) as owner:
                owner.execute('SELECT pg_advisory_lock(%s)',(reuse.LOCK_KEY,))
                try:authority._validate_archive_objects(conn,**arguments)
                except authority.BackupRuntimeUnavailable:
                    print(json.dumps({'scenario':scenario,'competing_owner_refused':True}));return
                raise AssertionError('concurrent native byte scrub was admitted')
        if scenario=='expire':
            raw=conn.execute('SELECT pg_read_binary_file(%s)',(reuse.NAME,)).fetchone()[0]
            value=json.loads(bytes(raw));value['proof']['completed_uptime']-=301
            value['signature']=reuse._signature(value['proof'])
            conn.execute(reuse._publish_sql(reuse._canonical(value)))
        if scenario=='corrupt':
            program=('sh -ceu '+shlex.quote(f"printf x | dd of={root}/{names[0]} conv=notrunc status=none")).replace("'","''")
            conn.execute(f"COPY (SELECT 'synthetic') TO PROGRAM '{program}'")
            try:authority._validate_archive_objects(conn,**arguments)
            except authority.BackupRuntimeRefused:
                raw=conn.execute('SELECT pg_read_binary_file(%s)',(reuse.NAME,)).fetchone()[0]
                assert json.loads(bytes(raw))['proof']['outcome']=='INVALID'
                print(json.dumps({'scenario':scenario,'corruption_refused':True,'positive_invalidated':True}));return
            raise AssertionError('native archive corruption granted reuse')
        _,hashed,full=authority._validate_archive_objects(conn,**arguments)
        assert (hashed,full)==((4,True) if scenario in {'prime','expire'} else (0,False))
        conn.rollback()  # The receipt cannot commit caller-owned SQL work.
        print(json.dumps({'scenario':scenario,'hashed_objects':hashed,'full_scrub':full,
            'fresh_process':True,'actual_postgresql_file_and_lock_authority':True}))


if __name__=='__main__':main()
