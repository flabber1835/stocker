#!/usr/bin/env python3
"""24x7 reviewed deployment entry.

A fresh shadow lineage has a genuine session-level timing constraint: its first
candidate must use source-final data and commit before the following XNYS open.
That constraint must not become an installation-time window.

For a brand-new shadow/dual lineage this entry installs/promotes/quiesces exactly
as the hardened deployer already does, then waits under the durable disabled +
kill-switch fence until a causally eligible first close exists.  It performs the
normal authoritative data refresh, derives a new exact publication binding from
the promoted runtime, records that rebind, and only then starts shadow genesis.

Existing shadow lineages are not rebound.  Their immutable genesis continues to
own its original publication identity and the ordinary shadow service handles
one-session waiting/catch-up.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
import time

import sentinel_autonomous_deploy as core
import sentinel_autonomous_deploy_bootstrap as bootstrap


_SOURCE_FINAL_CODE = r'''
import json
from datetime import datetime, timezone
from sentinel.feed import calendar
from sentinel.shadow_runtime import publication_not_before

now = datetime.now(timezone.utc)
latest = calendar.latest_closed_session(now)
latest_final = publication_not_before(latest)
following = calendar.next_session(latest)
following_open, _ = calendar.session_window(following)
following_open = following_open.astimezone(timezone.utc)
if now < latest_final:
    target = latest
    ready_at = latest_final
elif now < following_open:
    target = latest
    ready_at = now
else:
    target = following
    ready_at = publication_not_before(target)
print('SENTINEL_DEPLOY_SOURCE_FINAL=' + json.dumps({
    'target_session': target,
    'ready': now >= ready_at,
    'ready_at': ready_at.astimezone(timezone.utc).isoformat().replace('+00:00','Z'),
    'now': now.isoformat().replace('+00:00','Z'),
}, sort_keys=True))
'''.strip()


_GENESIS_STATE_CODE = r'''
import json, os
from sentinel.feed import store
from sentinel.shadow_observation import PostgresShadowObservationStore
c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
try:
    observation_id = os.environ.get('SENTINEL_SHADOW_OBSERVATION_ID', 'primary')
    genesis = PostgresShadowObservationStore(
        c, observation_id=observation_id).genesis()
    print('SENTINEL_DEPLOY_SHADOW_GENESIS=' + json.dumps({
        'exists': genesis is not None,
        'first_session': (genesis or {}).get('first_session'),
    }, sort_keys=True))
finally:
    c.rollback(); c.close()
'''.strip()


class InstallAnytimeBootstrapDeploy(bootstrap.BootstrapDeploy):
    """Add a fenced, causal genesis staging boundary to reviewed shadow deploys."""

    def _container_json(self, code: str, marker: str):
        result = self.runner.run(self.base_compose + [
            '--profile', 'cli', 'run', '--rm', '-T', '--no-deps',
            '--entrypoint', 'python', 'sentinel', '-c', code], capture=True)
        for line in (result.stdout or '').splitlines():
            if line.startswith(marker):
                try:
                    value = json.loads(line[len(marker):])
                except json.JSONDecodeError as exc:
                    raise core.DeployRefused(
                        '24x7 deployment probe returned malformed JSON') from exc
                if isinstance(value, dict):
                    return value
        raise core.DeployRefused('24x7 deployment probe returned no evidence')

    def _shadow_genesis_exists(self) -> bool:
        value = self._container_json(
            _GENESIS_STATE_CODE, 'SENTINEL_DEPLOY_SHADOW_GENESIS=')
        if type(value.get('exists')) is not bool:
            raise core.DeployRefused(
                'shadow genesis existence probe is malformed')
        return bool(value['exists'])

    def _wait_for_causal_genesis_session(self) -> str:
        """Wait under the existing durable execution fence, with no broker call."""
        last_target = None
        while True:
            self._assert_wait_fence()
            value = self._container_json(
                _SOURCE_FINAL_CODE, 'SENTINEL_DEPLOY_SOURCE_FINAL=')
            target = str(value.get('target_session') or '')
            ready_at = str(value.get('ready_at') or '')
            if not target or type(value.get('ready')) is not bool or not ready_at:
                raise core.DeployRefused(
                    'source-final staging probe is malformed')
            if value['ready'] is True:
                return target
            if target != last_target:
                self._write_deployment_state(
                    'WAITING_FOR_SOURCE_FINAL', attempt=1,
                    failures=[{
                        'name': 'source finality',
                        'status': 'WAITING',
                        'detail': 'fresh shadow genesis is waiting for fixed reviewed source-final boundary',
                        'value': {
                            'target_session': target,
                            'ready_at': ready_at,
                        },
                    }])
                print('\nDEPLOYMENT STAGED: WAITING_FOR_SOURCE_FINAL', flush=True)
                print('  automation: disabled and kill switch engaged', flush=True)
                print('  target session: %s' % target, flush=True)
                print('  source final at: %s' % ready_at, flush=True)
                last_target = target
            # Polling is bounded but the installation itself has no arbitrary
            # wall-clock deadline. The next source-final boundary is determined
            # by XNYS + the reviewed Sharadar timing policy.
            time.sleep(min(self.cfg.data_retry_seconds, 300))

    def _rebind_fresh_genesis_publication(self, target_session: str) -> None:
        reviewed = self.reviewed_validation
        if reviewed is None or reviewed.mode not in {'shadow', 'dual'}:
            return

        def invoke(argv, **_kwargs):
            return self.runner.run(argv, capture=True)

        current = core._current_data_publication_subject(
            reviewed, env=self.env, invoke=invoke)
        digest = core._validation_subject_digest('data_publication', current)
        old = reviewed.data_publication_sha256
        if not core._HEX64.fullmatch(digest):
            raise core.DeployRefused(
                'fresh shadow genesis publication digest is malformed')
        reviewed.data_publication_sha256 = digest
        updates = {'SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256': digest}
        self._persist_deploy_facts(updates)
        self.env.update(updates)
        self.runner.env.update(updates)
        evidence = {
            'schema': 'sentinel.shadow-genesis-publication-rebind/1',
            'observed_at': core._utc_text(core._utcnow()),
            'target_session': target_session,
            'previous_reviewed_publication_sha256': old,
            'genesis_publication_sha256': digest,
            'validated_source_identity_sha256': reviewed.source_identity_sha256,
            'validation_bundle_sha256': reviewed.bundle_sha256,
            'authority': 'SHADOW_GENESIS_ONLY_NOT_BROKER_AUTHORITY',
        }
        path = self.attempt_dir / 'shadow-genesis-publication-rebind.json'
        path.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + '\n',
            encoding='utf-8')

    def start_fenced_runtime(self):
        reviewed = self.reviewed_validation
        fresh_shadow = (
            reviewed is not None
            and reviewed.mode in {'shadow', 'dual'}
            and not self._shadow_genesis_exists())
        if fresh_shadow:
            target = self._wait_for_causal_genesis_session()
            # Use the existing hardened vendor-publication/readiness machinery
            # only after the fixed source-final boundary has elapsed.
            self.refresh_data()
            self._rebind_fresh_genesis_publication(target)
        return super().start_fenced_runtime()


def main(argv=None) -> int:
    # bootstrap.main resolves config/account/key facts and invokes this symbol.
    bootstrap.BootstrapDeploy = InstallAnytimeBootstrapDeploy
    return bootstrap.main(argv)


if __name__ == '__main__':
    raise SystemExit(main())
