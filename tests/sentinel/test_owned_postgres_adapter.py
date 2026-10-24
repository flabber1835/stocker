"""Mock-only ownership refusals; this module never opens a socket or database."""
import re

import pytest

from tests.support import postgres
from tests.support import private_postgres16 as private


TOKEN='a'*32
SYSTEM='7698561349436297260'
DATABASE='sentinel_qualification_'+TOKEN
URL='postgresql://postgres@127.0.0.1:5432/'+DATABASE


class Result:
    def __init__(self,rows): self.rows=rows
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows


class Server:
    def __init__(self):
        self.version='160014';self.system=SYSTEM;self.markers=[(True,TOKEN)]
        self.endpoint=(DATABASE,'postgres','127.0.0.1',5432)
        self.databases={};self.statements=[];self.connections=[];self.oid=100

    def connect(self,url,*,autocommit):
        assert url==URL and autocommit is True
        owner=self
        class Connection:
            closed=False
            def execute(self,query,params=()):
                text=query if isinstance(query,str) else query.as_string()
                owner.statements.append((text,params))
                if text=='SHOW server_version_num': return Result([(owner.version,)])
                if text=='SELECT system_identifier::text FROM pg_control_system()': return Result([(owner.system,)])
                if text=='SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port()':
                    return Result([owner.endpoint])
                if text=='SELECT id,ownership_token FROM public.sentinel_private_qualification_owner': return Result(owner.markers)
                if text=='SELECT oid FROM pg_database WHERE datname=%s':
                    value=owner.databases.get(params[0]);return Result([] if value is None else [(value[0],)])
                if text=='SELECT oid,datdba::regrole::text FROM pg_database WHERE datname=%s':
                    value=owner.databases.get(params[0]);return Result([] if value is None else [value])
                created=re.fullmatch('CREATE DATABASE "(sentinel_case_[0-9a-f]{32})" TEMPLATE template0',text)
                if created:
                    name=created.group(1);assert name not in owner.databases
                    owner.oid+=1;owner.databases[name]=(owner.oid,'postgres');return Result([])
                dropped=re.fullmatch('DROP DATABASE "(sentinel_case_[0-9a-f]{32})"',text)
                if dropped:
                    del owner.databases[dropped.group(1)];return Result([])
                raise AssertionError(text)
            def close(self): self.closed=True
        conn=Connection();self.connections.append(conn);return conn


@pytest.fixture
def server(monkeypatch):
    value=Server()
    monkeypatch.setattr(private,'_ACTIVE',None)
    monkeypatch.setattr(private,'_connect',value.connect)
    monkeypatch.setattr(postgres,'_EphemeralPostgres',object())
    return value


@pytest.mark.parametrize('url',[
    'postgresql://postgres@localhost:5432/'+DATABASE,
    'postgresql://postgres@192.0.2.1:5432/'+DATABASE,
    'postgresql://postgres@127.0.0.1:5433/'+DATABASE,
    URL+'?options=-csearch_path=foreign',
    URL+'?host=/var/run/postgresql',
    URL+'#fragment',
    URL.replace('postgres@','postgres:password@'),
    URL.replace('postgres@','other@'),
    URL.replace(DATABASE,'production'),
    URL.replace(DATABASE,'sentinel_qualification_'+'b'*32),
    URL.replace('/'+DATABASE,'/%2f'+DATABASE),
    URL.replace('postgresql:','postgres:'),
    'dbname=production host=/var/run/postgresql',
])
def test_foreign_or_option_bearing_dsn_is_refused_before_connect(server,url):
    with pytest.raises(private.PrivatePostgresRefused,match='DSN_REFUSED'):
        private.activate(url,SYSTEM,TOKEN)
    assert server.connections==[] and private._ACTIVE is None


@pytest.mark.parametrize(('field','value','reason'),[
    ('version','160013','VERSION_REFUSED'),
    ('version','170000','VERSION_REFUSED'),
    ('system','123456','FOREIGN_SYSTEM'),
    ('markers',[(True,'b'*32)],'FOREIGN_OWNER'),
    ('markers',[],'FOREIGN_OWNER'),
    ('markers',[(True,TOKEN),(True,TOKEN)],'FOREIGN_OWNER'),
    ('endpoint',('production','postgres','127.0.0.1',5432),'ENDPOINT_CHANGED'),
    ('endpoint',(DATABASE,'other','127.0.0.1',5432),'ENDPOINT_CHANGED'),
    ('endpoint',(DATABASE,'postgres','192.0.2.1',5432),'ENDPOINT_CHANGED'),
])
def test_actual_server_identity_is_verified_before_substitution(server,field,value,reason):
    before=postgres._EphemeralPostgres
    setattr(server,field,value)
    with pytest.raises(private.PrivatePostgresRefused,match=reason):
        private.activate(URL,SYSTEM,TOKEN)
    assert private._ACTIVE is None and postgres._EphemeralPostgres is before
    assert all(conn.closed for conn in server.connections)
    assert not any(text.startswith(('CREATE','DROP')) for text,_ in server.statements)


def test_instances_create_and_drop_only_their_distinct_acknowledged_database(server):
    private.activate(URL,SYSTEM,TOKEN)
    first=postgres._EphemeralPostgres();second=postgres._EphemeralPostgres()
    with pytest.raises(private.PrivatePostgresRefused,match='NOT_STARTED'): first.sync_dsn
    first.start();second.start()
    assert first.sync_dsn!=second.sync_dsn
    first_name=first._created[0];second_name=second._created[0]
    assert set(server.databases)=={first_name,second_name}
    first.stop();first.stop()
    assert set(server.databases)=={second_name}
    second.stop();assert server.databases=={}
    assert all(conn.closed for conn in server.connections)
    drops=[text for text,_ in server.statements if text.startswith('DROP')]
    assert drops==[f'DROP DATABASE "{first_name}"',f'DROP DATABASE "{second_name}"']


def test_endpoint_probe_normalizes_inet_mask_before_exact_ipv4_host_check(server):
    private.activate(URL,SYSTEM,TOKEN)
    assert ('SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port()',()) in server.statements


@pytest.mark.parametrize('damage',['system','token','oid','owner','name'])
def test_stop_revalidates_private_host_and_exact_created_database(server,damage):
    private.activate(URL,SYSTEM,TOKEN);instance=postgres._EphemeralPostgres();instance.start()
    name,oid,owner=instance._created
    if damage=='system': server.system='123456'
    elif damage=='token': server.markers=[(True,'b'*32)]
    elif damage=='oid': server.databases[name]=(oid+1,owner)
    elif damage=='owner': server.databases[name]=(oid,'other')
    else: instance._name='sentinel_case_'+'b'*32
    with pytest.raises(private.PrivatePostgresRefused): instance.stop()
    assert name in server.databases
    assert not any(text.startswith('DROP') for text,_ in server.statements)
    assert all(conn.closed for conn in server.connections)


@pytest.mark.parametrize('method',['enable_archive','archive','backup','restore','verify_backup','restart'])
def test_physical_and_backup_methods_refuse_without_metadata_or_process_operations(server,method):
    private.activate(URL,SYSTEM,TOKEN);instance=postgres._EphemeralPostgres()
    before=list(server.statements)
    with pytest.raises(private.PrivatePostgresRefused,match='FORBIDDEN'): getattr(instance,method)()
    assert server.statements==before


def test_second_activation_cannot_replace_current_owner(server):
    private.activate(URL,SYSTEM,TOKEN)
    before=len(server.connections)
    with pytest.raises(private.PrivatePostgresRefused,match='ALREADY_ACTIVATED'):
        private.activate(URL,SYSTEM,TOKEN)
    assert len(server.connections)==before
