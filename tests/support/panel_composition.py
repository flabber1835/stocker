"""Exercise the installed signed composition and publication boundaries."""
import hashlib

from sentinel.panel import composition, projection_service


def isolate_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(composition, 'path', lambda instance:
        tmp_path / (hashlib.sha256(instance.encode()).hexdigest() + '.json'))


def compose_and_publish(database_url, owner_id, state_dir, instance, prior_failed=False):
    composition.collect(database_url, owner_id, state_dir, instance)
    return projection_service.publish_once(database_url, owner_id, state_dir, instance, prior_failed)
