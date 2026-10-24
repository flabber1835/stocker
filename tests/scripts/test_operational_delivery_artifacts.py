"""Only exact reviewed same-image role artifacts extend local delivery scope."""
import json
from pathlib import Path

import pytest

from scripts.sentinel_local_delivery import builder
from scripts.sentinel_local_delivery.model import DeliveryRefused
from scripts.sentinel_local_delivery.qualification import sha256_file


def test_sender_has_coverage_authentication_without_broker_credentials():
    import yaml
    root = Path(__file__).resolve().parents[2]
    services = yaml.safe_load((root/'docker-compose.sentinel-automation.yml').read_text(encoding='utf8'))['services']
    sender = services['sentinel-alert-dispatcher']['environment']
    collector = services['sentinel-execution-collector']['environment']
    assert sender['SENTINEL_PUBLICATION_RECEIPT_KEY'] == '${SENTINEL_PUBLICATION_RECEIPT_KEY:?set SENTINEL_PUBLICATION_RECEIPT_KEY}'
    assert sender['ALPACA_API_KEY'] == sender['ALPACA_SECRET_KEY'] == ''
    assert collector['SENTINEL_PUBLICATION_RECEIPT_KEY'] == sender['SENTINEL_PUBLICATION_RECEIPT_KEY']
    assert 'SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY' not in collector


@pytest.mark.parametrize('name', sorted(builder.REVIEWED_HOST_ARTIFACTS))
def test_reviewed_operational_artifact_still_requires_exact_approved_hash(tmp_path, name):
    path = tmp_path/'approved.json'
    path.write_text(json.dumps([name]), encoding='utf8')
    expected = sha256_file(path)
    assert builder.allowed_delta(path, expected) == [name]
    path.write_text(json.dumps([name, 'Dockerfile.sentinel']), encoding='utf8')
    with pytest.raises(DeliveryRefused, match='APPROVED_DELTA_CHANGED'):
        builder.allowed_delta(path, expected)


@pytest.mark.parametrize('name', [
    'docker-compose.sentinel.yml', 'docker-compose.sentinel-backup.yml',
    'Dockerfile.sentinel', '.env', '.env.example', '../README.md',
    'docker-compose.other.yml', 'requirements.txt',
])
def test_role_artifact_change_cannot_admit_other_configuration(tmp_path, name):
    path = tmp_path/'approved.json'
    path.write_text(json.dumps([name]), encoding='utf8')
    with pytest.raises(DeliveryRefused, match='APPROVED_DELTA_PATH'):
        builder.allowed_delta(path, sha256_file(path))
