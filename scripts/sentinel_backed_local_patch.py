"""Explicit owner-authorized backed PAPER application roll; no broker writes.

Reuse the qualified source-layer builder and the existing digest-linked drain /
application handoff. The historical archive-off command retains its own guards.
"""
from contextlib import contextmanager, ExitStack
import fcntl
import json
import os
from pathlib import Path
import re
import sys

from sentinel_local_delivery import builder, cli
from sentinel_local_delivery.coordinator import Delivery
from sentinel_local_delivery.host import Host, SERVICES
from sentinel_local_delivery.model import DeliveryRefused, Journal, read_json, require
from sentinel_local_delivery.qualification import sha256_file
from sentinel_lock_ownership import owns_exclusive_flock

COMPOSE = ('docker-compose.sentinel.yml', 'docker-compose.sentinel-backup.yml',
           'docker-compose.sentinel-automation.yml')
IMAGE_SERVICES = (*SERVICES, 'sentinel', 'sentinel-authorized-cli')


def immutable_image_overlay(folder, image):
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', image), 'BACKED_OVERLAY_IMAGE_INVALID')
    path = folder/('application-images-'+image.removeprefix('sha256:')+'.json')
    raw = (json.dumps({'services': {name: {'image': image, 'pull_policy': 'never'}
        for name in IMAGE_SERVICES}}, sort_keys=True, separators=(',', ':'))+'\n').encode()
    require(not path.is_symlink(), 'BACKED_IMAGE_OVERLAY_UNSAFE')
    if not path.exists():
        with path.open('xb') as stream:
            os.chmod(path, 0o600)
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    require(path.read_bytes()==raw, 'BACKED_IMAGE_OVERLAY_CHANGED')
    return path


def postgres_facts(item):
    mounts = [m for m in item['Mounts'] if m['Destination']=='/var/lib/postgresql/data']
    require(item['State']['Running'] and len(mounts)==1
        and mounts[0]['Type']=='volume' and mounts[0]['Name']=='sentinel_sentinel_pgdata',
        'BACKED_POSTGRES_VOLUME_CHANGED')
    require('archive_mode=on' in item['Config']['Cmd'], 'BACKED_ARCHIVE_OFF_REFUSED')
    return dict(container=item['Id'], image=item['Image'], started=item['State']['StartedAt'],
        volume=mounts[0]['Name'], source=mounts[0]['Source'], command=item['Config']['Cmd'])


def predecessor_witness(path, *, inspect_image=None, trail=()):
    """Consume completed receipts without asserting another activation."""
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts
        and not any(item.is_symlink() for item in (path,*path.parents)),
        'BACKED_PREDECESSOR_PATH_UNSAFE')
    sha256_file(path)  # Refuse symlinks and missing receipt files before resolve.
    selected = path.resolve()
    require(len(trail)<16 and selected not in trail, 'BACKED_PREDECESSOR_CHAIN_INVALID')
    record = read_json(selected)
    if record.get('schema')=='sentinel.activation-receipt/1':
        require(selected.name=='activation-receipt.json'
            and record.get('operational_ready') is True
            and record.get('activation_mode')=='dual' and record.get('completed_at'),
            'BACKED_ACTIVE_PREDECESSOR_REQUIRED')
        root = selected.parents[5]
        require((root/'.git').exists(), 'BACKED_PREDECESSOR_ROOT_INVALID')
        image=record['runtime_image']
        if inspect_image is not None:
            inspected=inspect_image(image)
            require(inspected['Config']['Labels']['org.opencontainers.image.revision']==record['git_commit'],
                'BACKED_PREDECESSOR_RUNTIME_CHANGED')
            image=inspected['Id']
        return dict(git_commit=record['git_commit'],runtime_image=image,
            control_generation=record['control_generation'],certificate_sha256=record['certificate_sha256'],
            roots=(root,),postgres=None,system=None,foundation_reference=record['runtime_image'])
    require(selected.name=='receipt.json' and record.get('stage')=='VERIFIED',
        'BACKED_VERIFIED_PREDECESSOR_REQUIRED')
    journal = Journal(selected.parent)
    require(journal.read()==record, 'BACKED_PREDECESSOR_JOURNAL_CHANGED')
    request = journal.request
    built = read_json(selected.parent/'build.json')
    candidate = request['candidate']
    require(built.get('schema')==builder.BUILD_SCHEMA
        and built.get('commit')==candidate['commit'] and built.get('image')==candidate['image']
        and built.get('source_identity')==candidate['source_identity']
        and built.get('source')==request['source'] and built.get('deployment')==request['deployment']
        and built.get('foundation')==request['predecessor'], 'BACKED_PREDECESSOR_BUILD_CHANGED')
    qualification = built['qualification']
    require(qualification['report_path']==request['qualification']['report_path']
        and qualification['report_sha256']==request['qualification']['report_sha256']
        and sha256_file(qualification['report_path'])==qualification['report_sha256'],
        'BACKED_PREDECESSOR_QUALIFICATION_CHANGED')
    report = read_json(qualification['report_path'])
    require(report.get('commit')==candidate['commit'] and report.get('final') is True
        and report.get('source_files_unchanged') is True
        and report.get('source_files')==request['qualification']['source_files'],
        'BACKED_PREDECESSOR_QUALIFICATION_SUBJECT_CHANGED')
    prior = built['predecessor_receipt']
    require(sha256_file(prior['path'])==prior['sha256'], 'BACKED_PREDECESSOR_ANCHOR_CHANGED')
    anchor = predecessor_witness(prior['path'],inspect_image=inspect_image,trail=(*trail,selected))
    foundation = request['predecessor']
    require(foundation['commit']==anchor['git_commit']
        and foundation['image']==anchor['runtime_image'], 'BACKED_PREDECESSOR_FOUNDATION_CHANGED')
    pg, preserved = record['artifacts']['postgres'],record['artifacts']['preserved']
    require(pg==foundation['postgres'] and preserved['system']==foundation['system']
        and 'archive_mode=on' in pg['command']
        and (anchor['postgres'] is None or (pg==anchor['postgres']
            and preserved['system']==anchor['system'])), 'BACKED_PREDECESSOR_PRESERVATION_CHANGED')
    root=Path(request['source']).resolve()
    require((root/'.git').exists(), 'BACKED_PREDECESSOR_ROOT_INVALID')
    return dict(anchor,git_commit=candidate['commit'],runtime_image=candidate['image'],
        roots=tuple(dict.fromkeys((*anchor['roots'],root))),postgres=pg,system=preserved['system'],
        foundation_reference='sentinel-local-paper:'+candidate['commit'][:8])


class BackedHost(Host):
    supports_post_trade = True
    def __init__(self, request, operation_dir, *, predecessor_receipt=None):
        super().__init__(request,operation_dir)
        built = self.operation_dir/'build.json'
        self.predecessor_receipt = Path(predecessor_receipt or read_json(built)['predecessor_receipt']['path'])
        witness=predecessor_witness(self.predecessor_receipt,
            inspect_image=lambda ref:builder._inspect(self,ref))
        self.predecessor_roots=witness['roots']
        self.predecessor_root=self.predecessor_roots[0]

    def load_values(self):
        values = super().load_values()
        require(values.get('SENTINEL_LOCAL_PAPER_BACKUP_POLICY')=='REQUIRED_V1', 'BACKED_POLICY_REQUIRED')
        reference=values['SENTINEL_RUNTIME_IMAGE_REF']
        require(re.fullmatch(r'(?:[^\s]+@)?sha256:[0-9a-f]{64}',reference), 'BACKED_IMMUTABLE_IMAGE_REQUIRED')
        actual=builder._inspect(self,reference)['Id']
        require(actual==values['SENTINEL_RUNTIME_IMAGE_DIGEST']==values['SENTINEL_TEST_IMAGE_DIGEST'],
            'BACKED_RUNTIME_FACTS_DIFFER')
        # Resolve an immutable RepoDigest into its actual local image identity.
        # This field selects the same bytes; no certificate supplies the value.
        values.update(SENTINEL_RUNTIME_IMAGE_REF=actual,SENTINEL_LOCAL_PAPER_IMAGE=actual)
        return values

    def compose_paths(self, values):
        require(values['SENTINEL_GIT_COMMIT'] in {
            self.request['predecessor']['commit'],self.request['candidate']['commit']},
            'BACKED_COMPOSE_RUNTIME_OUTSIDE_REQUEST')
        role = ('candidate' if values['SENTINEL_GIT_COMMIT']==self.request['candidate']['commit']
                else 'predecessor')
        image = self.request[role]['image']
        require(values['SENTINEL_RUNTIME_IMAGE_DIGEST']==image
            and values['SENTINEL_LOCAL_PAPER_IMAGE']==image, 'BACKED_IMAGE_SELECTOR_CHANGED')
        overlay = immutable_image_overlay(self.operation_dir, image)
        return (*tuple(self.source/name for name in COMPOSE), overlay)

    def verify_compose(self, role):
        for name in COMPOSE:
            original=self.git_bytes('show',self.request['predecessor']['commit']+':'+name)
            require((self.source/name).read_bytes()==original==(self.deployment/name).read_bytes(),
                'BACKED_COMPOSITION_CHANGE_REFUSED')

    def install_compose(self):
        self.verify_compose('candidate')  # Exact existing archive-on topology.

    def postgres(self):
        actual=postgres_facts(self.container('sentinel-postgres'))
        require(actual==self.request['predecessor']['postgres'], 'BACKED_POSTGRES_IDENTITY_CHANGED')
        return actual

    def verify_candidate(self):
        identity=super().verify_candidate()
        image=self.request['candidate']['image']
        require(re.fullmatch(r'sha256:[0-9a-f]{64}',image), 'BACKED_CANDIDATE_IMAGE_INVALID')
        proof=self.sql("SELECT json_build_object('proof',proof,'age',extract(epoch FROM clock_timestamp()-observed_at),"
            "'authentic',evidence_sha256=encode(sha256(convert_to(proof::text,'UTF8')),'hex')) "
            "FROM sentinel_backup_evidence WHERE kind='RESTORE_DRILL' AND proof->>'runtime_image'='"+image+
            "' ORDER BY observed_at DESC,seq DESC LIMIT 1")
        require_restore(proof,self.request)
        return identity

    @contextmanager
    def owned(self):
        values=self.load_values()
        authority=Path(values['SENTINEL_AUTHORITY_ARTIFACTS_DIR'])
        paths=[authority/'activation-coordinator.lock',authority/'autonomous-deploy.lock',
            *(root/'artifacts/sentinel/go-validation/go-validation.lock'
              for root in self.predecessor_roots)]
        with ExitStack() as stack:
            for path in paths:
                require(path.is_absolute() and not path.is_symlink(), 'BACKED_OWNER_LOCK_PATH')
                path.parent.mkdir(parents=True,exist_ok=True)
                handle=stack.enter_context(path.open('a+'))
                try:fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError as exc:raise DeliveryRefused('ANOTHER_CANONICAL_OWNER_IS_ACTIVE') from exc
                require(owns_exclusive_flock(handle.fileno()), 'BACKED_OWNER_NOT_PROVEN')
            with super().owned():yield


def require_restore(value,request):
    require(isinstance(value,dict) and value.get('authentic') is True
        and 0<=float(value['age'])<=86400, 'BACKED_CANDIDATE_RESTORE_REQUIRED')
    proof=value['proof']
    require(proof.get('physical_only') is False
        and proof.get('runtime_image')==request['candidate']['image']
        and proof.get('system_identifier')==request['predecessor']['system']
        and re.fullmatch(r'[0-9a-f]{64}',proof.get('metadata_sha256',''))
        and re.fullmatch(r'base-[0-9]{8}T[0-9]{6}Z',proof.get('base_backup','')),
        'BACKED_CANDIDATE_RESTORE_SUBJECT_CHANGED')


def active_baseline(path, host):
    record=predecessor_witness(path,inspect_image=lambda ref:builder._inspect(host,ref))
    values=host.load_values()
    reference=record['runtime_image']
    image=builder._inspect(host,reference)
    require(image['Config']['Labels']['org.opencontainers.image.revision']==record['git_commit']
        and values['SENTINEL_GIT_COMMIT']==record['git_commit']
        and values['SENTINEL_RUNTIME_IMAGE_DIGEST']==image['Id'], 'BACKED_PREDECESSOR_RUNTIME_CHANGED')
    state=host.sql("SELECT json_build_object('system',(SELECT system_identifier::text FROM pg_control_system()),"
        "'generation',generation,'certificate',certificate_sha256) FROM sentinel_automation_control WHERE id=1")
    require(state['generation']==record['control_generation']
        and state['certificate']==record['certificate_sha256'], 'BACKED_PREDECESSOR_AUTHORITY_CHANGED')
    pg=postgres_facts(host.container('sentinel-postgres'))
    require(record['postgres'] is None or (pg==record['postgres'] and state['system']==record['system']),
        'BACKED_VERIFIED_POSTGRES_CHANGED')
    # The primary command must equal the unchanged canonical backed Compose graph.
    configuration=json.loads(host.compose(values,'config','--format','json').stdout)
    require(pg['command']==configuration['services']['sentinel-postgres']['command'],
        'BACKED_POSTGRES_COMPOSITION_CHANGED')
    return dict(commit=record['git_commit'],image=image['Id'],postgres=pg,system=state['system'])


def main(argv=None):
    args=cli.parser().parse_args(argv)
    folder=Path(args.operation_dir).resolve()
    try:
        if args.command=='build':
            folder=builder.safe_directory(folder,create=True)
            def factory(request,op):return BackedHost(request,op,predecessor_receipt=args.predecessor_receipt)
            draft=factory(dict(source=args.source,deployment=args.deployment),folder)
            witness=predecessor_witness(args.predecessor_receipt,
                inspect_image=lambda ref:builder._inspect(draft,ref))
            # The draft graph needs only the two already bound source revisions.
            draft.request.update(predecessor=dict(commit=witness['git_commit'],
                image=builder._inspect(draft,witness['runtime_image'])['Id']),candidate=dict(commit=args.commit))
            result=builder.build(source=args.source,deployment=args.deployment,
                predecessor_receipt=args.predecessor_receipt,qualification=args.qualification,
                qualification_sha256=args.qualification_sha256,approved_delta=args.allowed_delta,
                approved_delta_sha256=args.allowed_delta_sha256,operation_dir=folder,commit=args.commit,
                host_type=factory,baseline_reader=lambda path:active_baseline(path,draft),
                foundation_reference=witness['foundation_reference'])
            output=dict(build_record=str(folder/'build.json'),build_sha256=sha256_file(folder/'build.json'),
                commit=result['commit'],image=result['image'])
        elif args.command=='prepare':
            built=read_json(args.build_record)
            host=BackedHost(dict(source=built['source'],deployment=built['deployment'],
                predecessor=built['foundation'],candidate=dict(commit=built['commit'])),folder)
            cli.prepare(operation_dir=folder,build_record=args.build_record,build_sha256=args.build_sha256,
                operation_id=args.operation_id,host_type=BackedHost,
                baseline_reader=lambda path:active_baseline(path,host),handoff_mode=args.handoff_mode)
            output=cli.status(folder)
        elif args.command=='status':output=cli.status(folder)
        else:
            journal=Journal(folder);host=BackedHost(journal.request,folder)
            built=read_json(folder/'build.json')
            require(sha256_file(built['predecessor_receipt']['path'])==built['predecessor_receipt']['sha256']
                and built['foundation']==journal.request['predecessor'], 'BACKED_WITNESS_CHANGED')
            delivery=Delivery(host,journal)
            if args.one_stage:
                with host.owned():delivery.step()
            else:delivery.advance()
            output=cli.status(folder)
        print(json.dumps(output,sort_keys=True));return 0
    except (DeliveryRefused,OSError,ValueError,KeyError,TypeError) as exc:
        print('Backed local patch refused: '+str(exc),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
