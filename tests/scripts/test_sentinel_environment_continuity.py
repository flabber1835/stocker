"""Real private native-reader credentials survive privileged atomic replacement."""
from dataclasses import replace
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.scripts.test_sentinel_backed_local_patch import patch
from sentinel_local_delivery import environment as env
from sentinel_local_delivery.model import DeliveryRefused
import sentinel_env


@contextmanager
def separate_owner(case):
    case.process.terminate();case.process.wait(timeout=3)
    root=case.root.parent/'maintenance';(root/'scripts').mkdir(parents=True)
    script=root/'scripts/sentinel_backup_maintenance.py'
    script.write_bytes((case.root/'scripts/sentinel_backup_maintenance.py').read_bytes())
    case.old['SENTINEL_PUBLICATION_RECEIPT_KEY']='qualification-only-'+'x'*40
    case.new['SENTINEL_PUBLICATION_RECEIPT_KEY']=case.old['SENTINEL_PUBLICATION_RECEIPT_KEY']
    case.path.write_bytes(payload(case.old));(root/'.env').write_bytes(payload(case.old))
    subprocess.run(['git','init','-q',str(root)],check=True)
    subprocess.run(['git','-C',str(root),'add','scripts/sentinel_backup_maintenance.py'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=Private qualifier',
        '-c','user.email=qualifier@example.invalid','commit','-qm','private fixture'],check=True)
    commit=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    value=dict(schema='sentinel.native-maintenance-reader/1',deployment=str(case.root),source=str(root),
        commit=commit,script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
        environment_sha256=hashlib.sha256((root/'.env').read_bytes()).hexdigest())
    path=case.root/env.READER_SELECTION;path.parent.mkdir(parents=True)
    def write():path.write_text(json.dumps(dict(value=value,signature=env.reader_signature(
        value,case.old['SENTINEL_PUBLICATION_RECEIPT_KEY']))))
    write()
    def credentials():
        if os.geteuid()==0:os.setgroups([]);os.setgid(case.gid);os.setuid(case.uid)
    process=subprocess.Popen([sys.executable,'scripts/sentinel_backup_maintenance.py','--loop'],
        cwd=root,preexec_fn=credentials)
    try:yield SimpleNamespace(root=root,value=value,path=path,write=write,process=process)
    finally:
        if process.poll() is None:process.terminate()
        process.wait(timeout=3)


def test_authenticated_separate_native_owner_preserves_real_reader_continuity(private):
    with separate_owner(private) as owner:
        assert_real_reader_survives_install(private)
        assert owner.process.poll() is None


def test_host_fallback_policy_signature_is_required(private):
    with separate_owner(private) as owner:
        new=private.root.parent/'next-release';new.mkdir()
        (new/'.env').write_bytes(payload(private.old))
        env.handover_reader(private.root,new,private.old,private.old)
        (new/env.READER_SELECTION).unlink()
        path=new.parent/env.HOST_READER_SELECTION
        value=json.loads(path.read_bytes());value['signature']='0'*64
        path.write_text(json.dumps(value))
        with pytest.raises(env.DeliveryRefused):env.selected_reader(new,private.old)


def test_selected_policy_survives_release_staging_without_restarting_reader(private):
    with separate_owner(private) as owner:
        new=private.root.parent/'next-release';new.mkdir()
        (new/'.env').write_bytes(payload(private.old))
        env.handover_reader(private.root,new,private.old,private.old)
        assert env.selected_reader(new,private.old)[0]==owner.root
        (new/env.READER_SELECTION).unlink()
        assert env.selected_reader(new,private.old)[0]==owner.root
        assert env.readers(new,required=True,selected_root=owner.root)[0].pid==owner.process.pid
        assert owner.process.poll() is None


@pytest.mark.parametrize('fault',['key','source','signature','scope','existing'])
def test_handover_never_reselects_or_accepts_altered_policy(private,fault):
    with separate_owner(private) as owner:
        new=private.root.parent/'next-release';new.mkdir()
        (new/'.env').write_bytes(payload(private.old))
        values=dict(private.old)
        if fault=='key':
            private.old['SENTINEL_PUBLICATION_RECEIPT_KEY']='wrong-'+'z'*40
        elif fault=='source':(owner.root/'.env').write_text('changed')
        elif fault=='signature':owner.path.write_text('{}')
        elif fault=='scope':new=new/'foreign';new.mkdir();(new/'.env').write_text('')
        else:(new.parent/env.HOST_READER_SELECTION).write_text('{}')
        with pytest.raises(env.DeliveryRefused):env.handover_reader(private.root,new,private.old,values)
        assert not (new/env.READER_SELECTION).exists()


@pytest.mark.parametrize('fault',['signature','deployment','commit','script','environment','missing_process','fifo','hardlink'])
def test_separate_owner_selection_refuses_tampering_and_lost_owner(private,fault):
    with separate_owner(private) as owner:
        if fault=='signature':
            value=json.loads(owner.path.read_text());value['signature']='0'*64
            owner.path.write_text(json.dumps(value))
        elif fault=='deployment':owner.value['deployment']=str(private.root.parent);owner.write()
        elif fault=='commit':owner.value['commit']='0'*40;owner.write()
        elif fault=='script':(owner.root/'scripts/sentinel_backup_maintenance.py').write_text('changed')
        elif fault=='environment':(owner.root/'.env').write_bytes(payload(private.new))
        elif fault=='fifo':owner.path.unlink();os.mkfifo(owner.path)
        elif fault=='hardlink':os.link(owner.path,owner.path.with_suffix('.alias'))
        else:owner.process.terminate();owner.process.wait(timeout=3)
        with pytest.raises(DeliveryRefused):env.install(private.host,private.old,payload(private.new))
        assert private.path.read_bytes()==payload(private.old)


def test_separate_owner_signature_guard_has_executed_falsifier(private,monkeypatch):
    monkeypatch.setattr(env.hmac,'compare_digest',lambda *a:True)
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_separate_owner_selection_refuses_tampering_and_lost_owner(private,'signature')


def payload(values):
    return ''.join(k+'='+json.dumps(v)+'\n' for k,v in sorted(values.items())).encode()


@pytest.fixture
def private(tmp_path):
    root=tmp_path/'deployment';root.mkdir()
    if os.geteuid()==0:
        # All modified directories belong to this test's private basetemp.
        for path in (tmp_path,*tuple(tmp_path.parents)[:2]):path.chmod(0o755)
    root.chmod(0o755)
    scripts=root/'scripts';scripts.mkdir()
    script=scripts/'sentinel_backup_maintenance.py'
    script.write_text('import time\ntime.sleep(120)\n')
    uid,gid=(10001,10001) if os.geteuid()==0 else (os.geteuid(),os.getegid())
    def credentials():
        if os.geteuid()==0:os.setgroups([]);os.setgid(gid);os.setuid(uid)
    process=subprocess.Popen([sys.executable,'scripts/sentinel_backup_maintenance.py','--loop'],
        cwd=root,preexec_fn=credentials)
    previous={'SENTINEL_GIT_COMMIT':'1'*40,'SENTINEL_LOCAL_PAPER_BACKUP_POLICY':'REQUIRED_V1'}
    candidate=dict(previous,SENTINEL_GIT_COMMIT='2'*40)
    path=root/'.env';path.write_bytes(payload(previous));path.chmod(0o600)
    if os.geteuid()==0:os.chown(path,uid,gid)
    host=object.__new__(patch.Host);host.deployment=root
    host.literal=SimpleNamespace(parse_bytes=sentinel_env.parse_bytes)
    host.load_values=lambda:sentinel_env.parse_bytes(path.read_bytes())
    host.request={'candidate':{'commit':'2'*40,'image':'sha256:'+'b'*64,'source_identity':{'source':'3'*64}}}
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv)
        result=subprocess.run(argv,input=kwargs.get('data'),capture_output=True,timeout=kwargs['timeout'])
        if result.returncode:raise DeliveryRefused('PRIVATE_NATIVE_READER_REFUSED')
        return result
    host.run=run
    try:
        # Reading /proc is deterministic after Popen's exec handshake; no health
        # or maintenance job is started by the dummy process.
        yield SimpleNamespace(root=root,path=path,host=host,old=previous,new=candidate,
            process=process,uid=uid,gid=gid,calls=calls)
    finally:
        if process.poll() is None:process.terminate()
        process.wait(timeout=3)


def test_exact_private_native_owner_is_discovered_without_directory_owner_assumption(private):
    facts=env.readers(private.root,required=True)
    assert len(facts)==1
    fact=facts[0]
    assert (fact.pid,fact.uid,fact.gid)==(private.process.pid,private.uid,private.gid)
    assert fact.start_ticks>0
    if os.geteuid()==0:assert private.root.stat().st_uid!=fact.uid


def test_unrelated_long_argv_cannot_interrupt_exact_native_reader_discovery(private):
    unrelated=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)','x'*9000],cwd=private.root)
    try:
        facts=env.readers(private.root,required=True)
        assert len(facts)==1 and facts[0].pid==private.process.pid
    finally:
        unrelated.terminate();unrelated.wait(timeout=3)


def assert_real_reader_survives_install(case):
    before=case.path.stat()
    env.install(case.host,case.old,payload(case.new))
    after=case.path.stat()
    assert (after.st_uid,after.st_gid,stat.S_IMODE(after.st_mode))==(
        before.st_uid,before.st_gid,stat.S_IMODE(before.st_mode))
    assert (after.st_dev,after.st_ino)!=(before.st_dev,before.st_ino)
    assert case.path.read_bytes()==payload(case.new) and len(case.calls)==2
    assert not list(case.root.glob('.env.local-delivery-*'))


def test_real_private_native_reader_can_read_old_temp_and_installed_configuration(private):
    assert_real_reader_survives_install(private)


def test_generic_installer_uses_the_same_real_reader_and_preserves_archive_metadata(private):
    metadata=private.root/'local-delivery.json';metadata.write_text('{"original":"preserved"}')
    private.host.install_values(private.old,private.new)
    assert private.host.load_values()==private.new
    assert private.path.stat().st_uid==private.uid
    assert json.loads(metadata.read_text())['original']=='preserved'
    assert len(private.calls)==2


def test_unchanged_selection_checks_reader_without_replacing_file(private):
    before=private.path.stat()
    env.install(private.host,private.old)
    assert private.path.stat().st_ino==before.st_ino and len(private.calls)==1


def test_removed_owner_preservation_has_a_real_credential_falsifier(private,monkeypatch):
    if os.geteuid()!=0:pytest.skip('distinct credential ownership falsifier requires root')
    monkeypatch.setattr(env.os,'fchown',lambda *a:None)
    with pytest.raises(DeliveryRefused,match='METADATA_NOT_PRESERVED'):
        assert_real_reader_survives_install(private)
    assert private.path.read_bytes()==payload(private.old)


def test_root_readability_never_substitutes_for_actual_native_reader(private):
    if os.geteuid()!=0:pytest.skip('root/non-root access discriminator requires root')
    private.path.chmod(0)
    assert private.host.load_values()==private.old
    with pytest.raises(DeliveryRefused,match='NATIVE_READER_REFUSED'):
        env.install(private.host,private.old,payload(private.new))
    assert private.path.read_bytes()==payload(private.old)


def test_removed_native_reader_probe_has_an_executed_falsifier(private,monkeypatch):
    if os.geteuid()!=0:pytest.skip('root/non-root access discriminator requires root')
    monkeypatch.setattr(env,'_probe',lambda *a:None)
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_root_readability_never_substitutes_for_actual_native_reader(private)


def test_required_policy_cannot_install_without_its_native_owner(private):
    private.process.terminate();private.process.wait(timeout=3)
    with pytest.raises(DeliveryRefused,match='NATIVE_READER_UNAVAILABLE'):
        env.install(private.host,private.old,payload(private.new))
    assert private.path.read_bytes()==payload(private.old)


def test_archive_off_legacy_without_native_owner_still_preserves_metadata(private):
    private.process.terminate();private.process.wait(timeout=3)
    old=dict(private.old,SENTINEL_LOCAL_PAPER_BACKUP_POLICY='')
    new=dict(private.new,SENTINEL_LOCAL_PAPER_BACKUP_POLICY='')
    private.path.write_bytes(payload(old));before=private.path.stat()
    env.install(private.host,old,payload(new))
    after=private.path.stat()
    assert (after.st_uid,after.st_gid,stat.S_IMODE(after.st_mode))==(
        before.st_uid,before.st_gid,stat.S_IMODE(before.st_mode))
    assert not private.calls


@pytest.mark.parametrize('field',['pid','start_ticks','uid','gid','groups'])
def test_foreign_reader_contract_refuses_before_environment_replace(private,monkeypatch,field):
    fact=env.readers(private.root,required=True)[0]
    value=(fact.groups+(9999,)) if field=='groups' else getattr(fact,field)+1
    monkeypatch.setattr(env,'readers',lambda *a,**kw:(replace(fact,**{field:value}),))
    with pytest.raises(DeliveryRefused,match='NATIVE_READER_CHANGED'):
        env.install(private.host,private.old,payload(private.new))
    assert private.path.read_bytes()==payload(private.old)


def test_native_owner_exit_during_pre_replace_read_refuses_before_install(private):
    run=private.host.run
    def exit_after_read(argv,**kwargs):
        result=run(argv,**kwargs)
        private.process.terminate();private.process.wait(timeout=3)
        return result
    private.host.run=exit_after_read
    with pytest.raises(DeliveryRefused,match='NATIVE_READER_CHANGED'):
        env.install(private.host,private.old,payload(private.new))
    assert private.path.read_bytes()==payload(private.old)


@pytest.mark.parametrize('change',['inode','mode','bytes'])
def test_original_file_race_refuses_before_replace(private,change):
    run=private.host.run
    def race(argv,**kwargs):
        result=run(argv,**kwargs)
        if change=='inode':
            alternate=private.root/'external';alternate.write_bytes(payload(private.old))
            alternate.replace(private.path)
        elif change=='mode':private.path.chmod(0o640)
        else:private.path.write_bytes(payload(dict(private.old,SENTINEL_GIT_COMMIT='f'*40)))
        return result
    private.host.run=race
    with pytest.raises(DeliveryRefused,match='ORIGINAL_CHANGED'):
        env.install(private.host,private.old,payload(private.new))
    assert private.path.read_bytes()!=payload(private.new)


def test_unsupported_acl_or_xattr_is_not_silently_lost(private,monkeypatch):
    monkeypatch.setattr(env.os,'listxattr',lambda *a,**kw:['system.posix_acl_access'])
    with pytest.raises(DeliveryRefused,match='EXTENDED_METADATA_UNSUPPORTED'):
        env.install(private.host,private.old,payload(private.new))
    assert private.path.read_bytes()==payload(private.old)


def test_metadata_failure_leaves_original_intact(private,monkeypatch):
    def denied(*a):raise PermissionError('private metadata permission denied')
    monkeypatch.setattr(env.os,'fchown',denied)
    with pytest.raises(PermissionError):env.install(private.host,private.old,payload(private.new))
    assert private.path.read_bytes()==payload(private.old)


def test_symlink_environment_refuses(private):
    target=private.root/'private-original';private.path.rename(target);private.path.symlink_to(target)
    with pytest.raises(OSError):env.install(private.host,private.old,payload(private.new))
    assert target.read_bytes()==payload(private.old)


def test_same_reader_fence_guard_has_an_executed_falsifier(private,monkeypatch):
    monkeypatch.setattr(env,'_same_readers',lambda *a:None)
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_native_owner_exit_during_pre_replace_read_refuses_before_install(private)


def test_native_reader_timeout_is_closed_without_private_exception_data(private):
    import traceback
    private_value='private-native-timeout-canary-6843'
    def timeout(*a,**kw):
        raise subprocess.TimeoutExpired([private_value],5,
            output=private_value.encode(),stderr=private_value.encode())
    private.host.run=timeout
    with pytest.raises(DeliveryRefused,match='^ENVIRONMENT_NATIVE_READER_TIMEOUT$') as failure:
        env.install(private.host,private.old,payload(private.new))
    assert private_value not in ''.join(traceback.format_exception(failure.value))
    assert failure.value.__suppress_context__
    assert private.path.read_bytes()==payload(private.old)
    assert not list(private.root.glob('.env.local-delivery-*'))


def test_removed_native_reader_timeout_conversion_has_an_executed_falsifier(private,monkeypatch):
    monkeypatch.setattr(env,'subprocess',SimpleNamespace(TimeoutExpired=LookupError))
    with pytest.raises(subprocess.TimeoutExpired):
        test_native_reader_timeout_is_closed_without_private_exception_data(private)
