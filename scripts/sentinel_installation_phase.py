"""Certified software installation, independent of every financial GO gate."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import signal
import sys
import tempfile

import sentinel_autonomous_deploy as core
import sentinel_autonomous_deploy_bootstrap as bootstrap
import sentinel_ci_certification_verify as certification
import sentinel_env
from sentinel_env_writer import EnvWriteRefused
from sentinel_phase_records import publish_immutable


class InstallationConfig:
    """Only software/storage/operator configuration is required in this phase."""
    def __init__(self, env, mode='fenced'):
        self.env = dict(env)
        self.requested_mode = mode
        self.deployment_id = env.get('SENTINEL_DEPLOYMENT_ID', '').strip()
        self.account_id = env.get('SENTINEL_PAPER_ACCOUNT_ID', '').strip()
        self.runtime_repository = env.get('SENTINEL_RUNTIME_IMAGE_REPOSITORY',
                                         'ghcr.io/flabber1835/stocker/sentinel')
        self.test_repository = self.runtime_repository
        self.authority_dir = core._resolve_repo_path(env.get(
            'SENTINEL_AUTHORITY_ARTIFACTS_DIR', 'artifacts/sentinel/authority'))
        self.authority_dir.mkdir(parents=True, exist_ok=True)
        self.actor = env.get('SENTINEL_DEPLOY_ACTOR', 'sentinel-installation')
        self.health_timeout = core._int(env.get('SENTINEL_DEPLOY_HEALTH_TIMEOUT_SECONDS', '300'),
                                      name='health timeout', minimum=30, maximum=1800)
        self.heartbeat_seconds = core._int(env.get('SENTINEL_AUTOMATION_HEARTBEAT_SECONDS', '10'),
                                         name='heartbeat', minimum=1, maximum=300)


class InstallationDeploy(bootstrap.BootstrapDeploy):
    def build_promote(self):
        self.phase('installation: independently verify the exact signed CI runtime')
        self.resolve_compose()
        try:
            proof = certification.verify_current(
                root=core.ROOT, commit=self.commit,
                client=certification.GitHubReadClient(token=self.env.get('SENTINEL_GITHUB_READ_TOKEN')
                    or self.env.get('GITHUB_TOKEN') or self.env.get('GH_TOKEN')))
        except certification.CertificationVerificationRefused as exc:
            raise core.DeployRefused('%s: %s' % (exc.code, exc.detail)) from None
        reference = str(proof.get('certified_image') or '')
        if (proof.get('source_commit') != self.commit
                or proof.get('software_certification') != 'VERIFIED'
                or proof.get('required_ci_jobs') != 'PASS'):
            raise core.DeployRefused('software certification does not bind this exact release')
        _reference, digest = core._repo_digest(reference, self.cfg.runtime_repository)
        repository = self.cfg.runtime_repository
        if proof.get('image_digest') != digest:
            raise core.DeployRefused('signed software image digest disagrees')
        self.runner.run(['docker', 'pull', reference], timeout=600)
        inspected = self.runner.run(['docker', 'image', 'inspect', reference], capture=True, timeout=30)
        records = core._json_value(inspected.stdout.encode(), label='certified image inspection')
        if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
            raise core.DeployRefused('certified software image inspection is malformed')
        image = records[0]
        config = image.get('Config')
        labels = config.get('Labels') if isinstance(config, dict) else None
        if (not isinstance(labels, dict)
                or labels.get('org.opencontainers.image.revision') != self.commit
                or not isinstance(image.get('RepoDigests'), list)
                or reference not in (image.get('RepoDigests') or [])
                or core._DIGEST.fullmatch(str(image.get('Id') or '')) is None):
            raise core.DeployRefused('actual software image differs from signed certification')
        self.runtime_repo_digest = self.test_repo_digest = reference
        self.runtime_digest = self.test_digest = digest
        self._ci_single_runtime = True
        self.env.update({
            'SENTINEL_GIT_COMMIT': self.commit,
            'SENTINEL_RUNTIME_IMAGE_REF': reference,
            'SENTINEL_RUNTIME_IMAGE_REPOSITORY': repository,
            'SENTINEL_RUNTIME_IMAGE_DIGEST': digest,
            'SENTINEL_TEST_IMAGE_DIGEST': digest,
        })
        self.runner.env.update(self.env)
        publish_immutable(self.attempt_dir / 'ci-certified-runtime.json', proof)

    def quiesce_backup_and_migrate(self):
        super().quiesce_backup_and_migrate()
        # Only signed software plus a confirmed durable fence can replace the
        # selector. Financial readiness is neither consulted nor implied.
        state = self._automation_status()
        if state.get('enabled') is not False or state.get('kill_switch_engaged') is not True:
            raise core.DeployRefused('runtime selection requires disabled+killed execution')
        from sentinel_runtime_selection import _write_pointer
        _write_pointer(self.runtime_repo_digest)

    def start_fenced_runtime(self):
        self.phase('installation: create dormant exact financial services')
        before = self._automation_status()
        if before.get('enabled') is not False or before.get('kill_switch_engaged') is not True:
            raise core.DeployRefused('installation requires disabled+killed execution')
        self.runner.run(self._authorized_compose() + [
            '--profile', 'automation', '--profile', 'shadow', 'create',
            'sentinel-automation', 'sentinel-shadow'])
        if self._running_automation_containers():
            raise core.DeployRefused('financial automation unexpectedly running at installation completion')
        running = self.runner.run(['docker', 'ps', '-q',
            '--filter', 'label=com.docker.compose.project=sentinel',
            '--filter', 'label=com.docker.compose.service=sentinel-shadow'], capture=True)
        if running.stdout.strip():
            raise core.DeployRefused('shadow writer unexpectedly running at installation completion')
        after = self._automation_status()
        if after.get('enabled') is not False or after.get('kill_switch_engaged') is not True:
            raise core.DeployRefused('installation lost its durable execution fence')
        return after


def request_activation(installation, mode, *, bundle=None, confirmation=None):
    """Seal a separate request after software success; never import financial admission."""
    from sentinel_activation_coordinator import handoff
    from sentinel_phase_records import write_document
    receipt = installation.installation_receipt
    request = {
        'schema': 'sentinel.activation-request/1', 'mode': mode,
        'installation_receipt': str(receipt.resolve()),
        'installation_sha256': hashlib.sha256(receipt.read_bytes()).hexdigest(),
        'source_commit': installation.commit, 'checkout': str(core.ROOT.resolve()),
        'env_sha256': hashlib.sha256(core.ENV_PATH.read_bytes()).hexdigest(),
        'bundle': str(Path(bundle).resolve()) if bundle is not None else None,
        'bundle_sha256': confirmation,
    }
    requests = receipt.parent / 'activation-requests'
    requests.mkdir(mode=0o700, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='request-', dir=str(requests)))
    path = directory / 'activation-request.json'
    publish_immutable(path, request)
    state = handoff(path)
    write_document(directory / 'activation-handoff.json', state)
    print('installation complete; activation: ' + state['activation_state'], flush=True)
    print('activation request: ' + str(path), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--explain', action='store_true')
    parser.add_argument('--mode', choices=('shadow', 'dual', 'paper'))
    parser.add_argument('--activate-when-ready', action='store_true')
    parser.add_argument('--validation-bundle', type=Path)
    parser.add_argument('--confirm-reviewed-go')
    args = parser.parse_args(argv)
    if args.explain:
        print('signed software -> fence/storage/schema -> operator services -> dormant financial services '
              '-> immutable INSTALLED/FENCED receipt; preparation/activation is a separate host service')
        return 0
    if args.activate_when_ready and args.mode is None:
        parser.error('--activate-when-ready requires --mode')
    if args.validation_bundle is not None and not args.activate_when_ready:
        parser.error('financial evidence is valid only with --activate-when-ready')
    if (args.validation_bundle is None) != (args.confirm_reviewed_go is None):
        parser.error('an optional activation bundle requires its exact confirmation')
    if args.confirm_reviewed_go is not None and re.fullmatch('[0-9a-f]{64}', args.confirm_reviewed_go) is None:
        parser.error('activation bundle confirmation must be a SHA256')
    previous_signal = signal.signal(signal.SIGTERM, interrupt)
    try:
        from sentinel_env_writer import safe_update_dotenv
        bootstrap._safe_update_dotenv = core.update_dotenv = safe_update_dotenv
        env = core.merged_environment()
        sentinel_env.validate(env, profile='install')
        # Discovery preserves existing durable identity; it does not require a broker GET.
        env = bootstrap.discover(env, installation_only=True)
        cfg = InstallationConfig(env, args.mode or 'fenced')
        head = bootstrap._run(['git', 'rev-parse', 'HEAD'], env=env).stdout.strip()
        attempt = core._attempt_dir(cfg, head)
        runner = core.Runner(env, attempt / 'commands.log')
        obj = InstallationDeploy(cfg, runner, attempt)
        with core.DeploymentLock(cfg.authority_dir / 'autonomous-deploy.lock'):
            obj.run()
        if args.activate_when_ready:
            try:
                request_activation(obj, args.mode, bundle=args.validation_bundle,
                                   confirmation=args.confirm_reviewed_go)
            except (OSError, ValueError, core.DeployRefused) as exc:
                # Software completion is immutable even if the separate handoff needs repair.
                from sentinel_phase_records import write_document
                try:
                    write_document(obj.installation_receipt.parent / 'activation-handoff.json', {
                        'schema': 'sentinel.activation-handoff/1',
                        'activation_state': 'OPERATOR_ACTION_REQUIRED',
                        'reason': type(exc).__name__})
                except (OSError, ValueError):
                    print('activation handoff status could not be persisted; software is installed',
                          file=sys.stderr)
                print('activation request needs operator action: ' + type(exc).__name__, file=sys.stderr)
        return 0
    except KeyboardInterrupt:
        print('INSTALLATION INTERRUPTED: inspect retained installation and fence evidence', file=sys.stderr)
        return 130
    except (core.DeployRefused, EnvWriteRefused, OSError, ValueError) as exc:
        print('INSTALLATION REFUSED: ' + str(exc), file=sys.stderr)
        return 2
    finally:
        signal.signal(signal.SIGTERM, previous_signal)


def interrupt(_signal, _frame):
    raise KeyboardInterrupt


if __name__ == '__main__':
    raise SystemExit(main())
