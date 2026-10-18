"""Current Alpaca diagnostics preserve read-only authority and credential boundaries."""
import json

import pytest


def test_readonly_feed_diagnostic_selects_only_named_configuration(tmp_path):
    from tools.autonomy_feed_qualification import selected_config, backup_availability
    config = tmp_path / 'operator.env'
    original = 'ALPACA_API_KEY="data-key"\nALPACA_SECRET_KEY=data-secret\nOTHER_SECRET=private\n'
    config.write_text(original)
    selected = selected_config(config, {'ALPACA_API_KEY':'override', 'SENTINEL_PAPER_ACCOUNT_ID':'private-id'})
    assert selected == {'ALPACA_API_KEY':'override', 'ALPACA_SECRET_KEY':'data-secret'}
    assert config.read_text() == original
    missing = backup_availability({'SENTINEL_BACKUP_DIR':str(tmp_path/'missing'),
                                   'SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED':'1'})
    assert missing['status'] == 'NOT_PROVEN' and not missing['configured_target_present']
    present = backup_availability({'SENTINEL_BACKUP_DIR':str(tmp_path),
                                   'SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED':'1'})
    assert present['status'] == 'NOT_PROVEN'


def test_readonly_feed_diagnostic_container_has_no_account_or_database_authority():
    from tools.autonomy_feed_qualification import probe_command, PROBE_CODE
    command = probe_command('sha256:'+'a'*64)
    assert command[:4] == ['docker','run','--rm','-i']
    assert '--read-only' in command and '--cap-drop' in command
    assert '--volume' not in command and '--mount' not in command
    assert not any('DATABASE' in item or 'ACCOUNT_ID' in item or 'BACKUP_' in item for item in command)
    assert 'retained_go' not in PROBE_CODE and '/orders' not in PROBE_CODE
    assert PROBE_CODE.index('SENTINEL_IMAGE_SOURCE_REVISION') < PROBE_CODE.index('from sentinel.feed')
    assert '_bounds(day, day)' in PROBE_CODE
    compile(PROBE_CODE, '<provider-probe>', 'exec')


def test_readonly_feed_diagnostic_redacts_untrusted_provider_output():
    from tools.autonomy_feed_qualification import run_probe, MARKER
    import subprocess
    calls = []
    def runner(command, **kwargs):
        calls.append((command, kwargs))
        value = {'status':'FAIL', 'error_type':'credential-secret'}
        return subprocess.CompletedProcess(command,0,MARKER+json.dumps(value),'private-account-id')
    result = run_probe('sha256:'+'a'*64,'b'*40,
                       {'ALPACA_API_KEY':'credential-secret','ALPACA_SECRET_KEY':'other-secret'}, runner=runner)
    assert result['status'] == 'FAIL' and result['reason'] == 'PROVIDER_PROBE_OUTPUT_REFUSED'
    assert 'credential-secret' not in json.dumps(result) and 'private-account-id' not in json.dumps(result)
    assert 'credential-secret' not in ' '.join(calls[0][0])
    assert calls[0][1]['env']['ALPACA_API_KEY'] == 'credential-secret'


def test_readonly_feed_diagnostic_never_claims_complete_go(tmp_path, capsys):
    from tools.autonomy_feed_qualification import main
    output = tmp_path/'diagnostic'
    assert main(['--runtime-image','sha256:'+'a'*64,'--commit','b'*40,
                 '--output-dir',str(output),'--plan-only']) == 2
    report = json.loads((output/'report.json').read_text())
    assert report['status'] == report['source']['status'] == 'NOT_PROVEN'
    assert not report['financial_publication_attempted'] and report['broker_mutation_attempts'] == 0
    assert 'formation_restart_parity' in report['unexecuted']
    with pytest.raises(SystemExit):
        main(['--runtime-image','sha256:'+'a'*64,'--commit','b'*40,
              '--output-dir',str(output),'--plan-only'])



def test_readonly_feed_diagnostic_cleans_only_its_named_container_after_timeout():
    import subprocess
    from tools.autonomy_feed_qualification import run_probe
    calls = []
    def runner(command, **kwargs):
        calls.append((command,kwargs))
        if command[:2] == ['docker','run']:
            raise subprocess.TimeoutExpired(command,600)
        return subprocess.CompletedProcess(command,0,'','')
    with pytest.raises(subprocess.TimeoutExpired):
        run_probe('sha256:'+'a'*64,'b'*40,
                  {'ALPACA_API_KEY':'secret','ALPACA_SECRET_KEY':'secret2'},runner=runner)
    name = calls[0][0][calls[0][0].index('--name')+1]
    assert calls[1][0] == ['docker','rm','--force',name]
    assert name.startswith('sentinel-source-diagnostic-')
    assert not any(key in calls[1][1]['env'] for key in ('ALPACA_API_KEY','ALPACA_SECRET_KEY'))
