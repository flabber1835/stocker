"""Bounded Alpaca-only data renewal inside the already-fenced installer."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import time
import uuid

import sentinel_autonomous_deploy as core
import sentinel_go_validate as go

MARKER = "SENTINEL_INSTALL_SOURCE_REFRESH="
CODE = r'''
import json, os
from datetime import datetime, timezone
from sentinel import deployment_fence
from sentinel.feed import calendar, operational_snapshot, rolling_go_inputs, store
from sentinel.feed.rolling_jobs import JobDeadlineExceeded
from sentinel.backup_runtime_authority import BackupHorizonExceeded
c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
try:
    deployment_fence.require(c)
    c.rollback()
    rolling_go_inputs.require_schemas(c)
    target = os.environ['SENTINEL_INSTALL_SOURCE_TARGET']
    now = datetime.now(timezone.utc)
    opened, _ = calendar.session_window(calendar.next_session(target))
    if (target != operational_snapshot.source_final_session(now)
            or target != calendar.latest_closed_session(now) or now >= opened):
        result = {'status': 'WINDOW_EXPIRED', 'resume_job_id': None}
    else:
        try:
            prepared = rolling_go_inputs._prepare(
                c, target_session=target,
                absolute_deadline=rolling_go_inputs.deadline_from_host(
                    os.environ['SENTINEL_INSTALL_SOURCE_DEADLINE']),
                resume_job_id=os.environ.get('SENTINEL_INSTALL_RESUME_JOB_ID'))
            result = {'status': prepared['status'], 'resume_job_id': None}
        except BackupHorizonExceeded as exc:
            c.rollback()
            result = {'status': 'BACKUP_HORIZON_EXCEEDED',
                      'resume_job_id': exc.resume_job_id}
        except JobDeadlineExceeded:
            c.rollback()
            result = {'status': 'WINDOW_EXPIRED', 'resume_job_id': None}
        except rolling_go_inputs.RollingGoRefused as exc:
            if str(exc) != 'ROLLING_SOURCE_FINAL_TARGET_CHANGED':
                raise
            c.rollback()
            result = {'status': 'WINDOW_EXPIRED', 'resume_job_id': None}
    print('SENTINEL_INSTALL_SOURCE_REFRESH=' + json.dumps(result, sort_keys=True))
finally:
    c.rollback(); c.close()
'''.strip()


def refresh(deploy, *, timing, deadline):
    """Reuse canonical jobs; never start a shadow or acquire broker authority."""
    target = timing['target']
    if timing['frontier'] >= target:
        raise core.DeployRefused('source refresh requires a behind publication')
    resume = None
    # The same monotonic budget also bounds backup renewal and all retries.
    while True:
        deploy._assert_wait_fence()
        current = deploy._causal_timing()
        if (current['target'] != target or not deploy._timing_eligible(current)):
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise core.DeployRefused('installation source wait deadline exhausted')
        seconds = min(remaining, current['remaining_ms'] / 1000)
        cutoff = min(
            datetime.fromisoformat(current['execution_open_at']),
            datetime.now(timezone.utc) + timedelta(seconds=remaining))
        env = go._with_market_data_authority(deploy.env)
        env.update({
            'SENTINEL_INSTALL_SOURCE_TARGET': target,
            'SENTINEL_INSTALL_SOURCE_DEADLINE': cutoff.isoformat(),
        })
        if resume:
            env['SENTINEL_INSTALL_RESUME_JOB_ID'] = resume
        else:
            env.pop('SENTINEL_INSTALL_RESUME_JOB_ID', None)
        forwarded = (
            'ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'OPENFIGI_API_KEY',
            'SENTINEL_FEED_AUTHORIZED', 'SENTINEL_FEED_SERVICE_MODE',
            'SENTINEL_FEED_GIT_COMMIT', 'SENTINEL_FEED_RUNTIME_IMAGE_DIGEST',
            'SENTINEL_INSTALL_SOURCE_TARGET', 'SENTINEL_INSTALL_SOURCE_DEADLINE',
            'SENTINEL_INSTALL_RESUME_JOB_ID',
        )
        command = deploy.base_compose + [
            '--profile', 'cli', 'run', '--rm', '-T', '--no-deps',
        ] + [item for name in forwarded for item in ('--env', name)] + [
            '--entrypoint', 'python', 'sentinel', '-c', CODE,
        ]
        deploy.phase('data: refresh source-final Alpaca/OpenFIGI ' + target)
        completed = deploy.runner.run(
            command, capture=True, stream=True, timeout=seconds, env=env)
        values = [json.loads(line[len(MARKER):])
                  for line in (completed.stdout or '').splitlines()
                  if line.startswith(MARKER)]
        if len(values) != 1 or not isinstance(values[0], dict):
            raise core.DeployRefused('source refresh completion evidence unavailable')
        result = values[0]
        if set(result) != {'status', 'resume_job_id'}:
            raise core.DeployRefused('source refresh completion evidence malformed')
        deploy._assert_wait_fence()
        deploy._write_deployment_state(
            'SOURCE_REFRESH_' + str(result['status']), attempt=1, failures=[])
        if result['status'] in {'PUBLISHED', 'ALREADY_CURRENT', 'WINDOW_EXPIRED'}:
            if result['resume_job_id'] is not None:
                raise core.DeployRefused('source refresh success has unexpected resume authority')
            return
        if result['status'] != 'BACKUP_HORIZON_EXCEEDED':
            raise core.DeployRefused('source refresh refused its publication')
        try:
            resume = str(uuid.UUID(result['resume_job_id']))
        except (ValueError, TypeError, AttributeError):
            raise core.DeployRefused('source refresh backup resume identity invalid') from None
        deploy._create_backup(restore_drill=False, deadline=deadline)
