"""Test-only logical databases inside one explicitly owned private PG16 host.

The launcher owns the isolated container and its lifetime. This adapter never
starts a process, opens a filesystem path, or operates on a production database.
Each instance can drop only the database whose successful CREATE it recorded.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlsplit
import uuid

import psycopg
from psycopg import sql


class PrivatePostgresRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class _Host:
    url:str
    database:str
    system_identifier:str
    ownership_token:str


_ACTIVE:_Host|None=None
_connect=psycopg.connect


def _require(condition,reason):
    if not condition:
        raise PrivatePostgresRefused(reason)


def _host(url,system_identifier,ownership_token):
    _require(isinstance(url,str) and isinstance(system_identifier,str)
        and isinstance(ownership_token,str),'PRIVATE_PG_ARGUMENTS_INVALID')
    _require(re.fullmatch('[0-9a-f]{32}',ownership_token) is not None,
        'PRIVATE_PG_OWNERSHIP_TOKEN_INVALID')
    _require(re.fullmatch('[1-9][0-9]{0,19}',system_identifier) is not None
        and int(system_identifier)<2**64,'PRIVATE_PG_SYSTEM_IDENTIFIER_INVALID')
    _require(url=='postgresql://postgres@127.0.0.1:5432/sentinel_qualification_'+ownership_token,
        'PRIVATE_PG_DSN_REFUSED')
    try:
        value=urlsplit(url)
        valid=(value.scheme=='postgresql' and value.hostname=='127.0.0.1' and value.port==5432
            and value.username=='postgres' and value.password is None and not value.query
            and not value.fragment and value.path=='/sentinel_qualification_'+ownership_token
            and value.netloc=='postgres@127.0.0.1:5432')
    except (ValueError,TypeError):
        valid=False
    _require(valid,'PRIVATE_PG_DSN_REFUSED')
    return _Host(url,value.path[1:],system_identifier,ownership_token)


def _verify(conn,host):
    version=conn.execute('SHOW server_version_num').fetchone()
    _require(version is not None and str(version[0])=='160014','PRIVATE_PG_VERSION_REFUSED')
    system=conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()
    _require(system is not None and str(system[0])==host.system_identifier,
        'PRIVATE_PG_FOREIGN_SYSTEM')
    endpoint=conn.execute('SELECT current_database(),current_user,host(inet_server_addr()),'
        'inet_server_port()').fetchone()
    _require(endpoint is not None and tuple(endpoint)==(host.database,'postgres','127.0.0.1',5432),
        'PRIVATE_PG_ENDPOINT_CHANGED: '+repr(None if endpoint is None else tuple(endpoint)))
    marker=conn.execute('SELECT id,ownership_token FROM public.sentinel_private_qualification_owner').fetchall()
    _require(marker==[(True,host.ownership_token)],'PRIVATE_PG_FOREIGN_OWNER')


def _metadata(host):
    conn=_connect(host.url,autocommit=True)
    try:
        _verify(conn,host)
    except BaseException:
        conn.close()
        raise
    return conn


def _database_url(host,name):
    _require(re.fullmatch('sentinel_case_[0-9a-f]{32}',name) is not None,
        'PRIVATE_PG_DATABASE_NAME_INVALID')
    return 'postgresql://postgres@127.0.0.1:5432/'+name


class _PoolPostgres:
    def __init__(self):
        _require(_ACTIVE is not None,'PRIVATE_PG_NOT_ACTIVATED')
        self._host=_ACTIVE
        self._name='sentinel_case_'+uuid.uuid4().hex
        self._created=None
        self._attempted=False

    @property
    def sync_dsn(self):
        _require(self._created is not None,'PRIVATE_PG_INSTANCE_NOT_STARTED')
        return _database_url(self._host,self._name)

    def start(self):
        _require(not self._attempted,'PRIVATE_PG_INSTANCE_ALREADY_STARTED')
        self._attempted=True
        _database_url(self._host,self._name)
        conn=_metadata(self._host)
        try:
            _require(conn.execute('SELECT oid FROM pg_database WHERE datname=%s',(self._name,)).fetchone()
                is None,'PRIVATE_PG_DATABASE_ALREADY_EXISTS')
            conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(self._name)))
            row=conn.execute('SELECT oid,datdba::regrole::text FROM pg_database WHERE datname=%s',
                (self._name,)).fetchone()
            _require(row is not None and row[1]=='postgres','PRIVATE_PG_CREATE_NOT_CONFIRMED')
            self._created=(self._name,int(row[0]),row[1])
        finally:
            conn.close()

    def stop(self):
        if self._created is None:
            return
        name,oid,owner=self._created
        _database_url(self._host,name)
        _require(name==self._name,'PRIVATE_PG_DATABASE_IDENTITY_CHANGED')
        conn=_metadata(self._host)
        try:
            row=conn.execute('SELECT oid,datdba::regrole::text FROM pg_database WHERE datname=%s',
                (name,)).fetchone()
            _require(row is not None and (int(row[0]),row[1])==(oid,owner),
                'PRIVATE_PG_CREATED_DATABASE_CHANGED')
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
            self._created=None
        finally:
            conn.close()

    def _unsupported(self,*_args,**_kwargs):
        raise PrivatePostgresRefused('PRIVATE_PG_PHYSICAL_OR_BACKUP_OPERATION_FORBIDDEN')

    enable_archive=_unsupported
    archive=_unsupported
    backup=_unsupported
    restore=_unsupported
    verify_backup=_unsupported
    restart=_unsupported


def activate(url,system_identifier,ownership_token):
    """Validate the actual private host before substituting the test fixture."""
    global _ACTIVE
    host=_host(url,system_identifier,ownership_token)
    _require(_ACTIVE is None,'PRIVATE_PG_ALREADY_ACTIVATED')
    conn=_metadata(host)
    try:
        from tests.support import postgres
        _require(postgres._EphemeralPostgres is not _PoolPostgres,'PRIVATE_PG_ALREADY_ACTIVATED')
        _ACTIVE=host
        postgres._EphemeralPostgres=_PoolPostgres
    finally:
        conn.close()
