"""Owner-local PAPER build and resumable delivery commands."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
import sys

from . import builder
from .coordinator import Delivery
from .host import Host
from .model import (ACCESS_PATH_SCHEMA, POST_SCHEMA_ACCESS_PATH, DeliveryRefused, Journal,
                    SCHEMA, SUCCESSOR_SCHEMA, digest, handoff_mode, require,
                    utcnow, validate_request, write_new)
from .qualification import sha256_file, validate_report


def prepare(*, operation_dir, build_record, build_sha256, operation_id, host_type=Host,
            baseline_reader=None,handoff_mode='PRE_OPEN',canonical_proof_phase='PRE_DRAIN'):
    require(canonical_proof_phase in {'PRE_DRAIN',POST_SCHEMA_ACCESS_PATH},
            'REQUEST_CANONICAL_PROOF_PHASE')
    bootstrap = canonical_proof_phase == POST_SCHEMA_ACCESS_PATH
    if bootstrap:
        require(handoff_mode=='PRE_OPEN'
                and getattr(host_type,'supports_post_schema_access_path',False) is True,
                'ACCESS_PATH_BOOTSTRAP_REQUIRES_BACKED_PRE_OPEN')
    folder = builder.safe_directory(operation_dir,create=True)
    require(not (folder/'request.json').exists() and not (folder/'receipt.json').exists(),
            'DELIVERY_OPERATION_ALREADY_PREPARED')
    require(not (folder/'build-reference.json').exists()
            and not (folder/'build-reference.json').is_symlink(),
            'BUILD_ARTIFACT_ALREADY_REFERENCED')
    built = builder.pinned_build(build_record,build_sha256)
    require(isinstance(built,dict) and set(built) == {
        'schema','at','source','deployment','commit','image','tag','source_identity',
        'strategy_sha256','foundation','predecessor_receipt','qualification','allowed_delta',
        'changed_files','context','log','log_sha256','command'}
        and built['schema'] == builder.BUILD_SCHEMA, 'BUILD_RECORD_SHAPE')
    artifact = builder.safe_directory(Path(build_record).parent)
    external = artifact != folder
    require(not external or not any((folder/name).exists() or (folder/name).is_symlink()
            for name in ('build.json','build-started.json','source-context','build.log')),
            'BUILD_ARTIFACT_REFERENCE_AMBIGUOUS')
    require(Path(built['context']) == artifact/'source-context'
        and builder.safe_directory(built['context']) == artifact/'source-context'
        and Path(built['log']) == artifact/'build.log'
        and sha256_file(built['log']) == built['log_sha256'], 'BUILD_ARTIFACTS_CHANGED')
    require(not folder.is_relative_to(Path(built['source']).resolve()),
            'BUILD_EVIDENCE_INSIDE_QUALIFIED_SOURCE')
    predecessor = built['predecessor_receipt']
    require(sha256_file(predecessor['path']) == predecessor['sha256'], 'PREDECESSOR_RECEIPT_CHANGED')
    old = (baseline_reader or builder.baseline)(predecessor['path'])
    require(old == built['foundation'], 'BUILD_FOUNDATION_CHANGED')
    qualified = built['qualification']
    report = validate_report(qualified['report_path'],qualified['report_sha256'],built['source'],
        built['commit'],old['commit'])
    require(sorted(built['changed_files']) == built['allowed_delta'], 'BUILD_DELTA_CHANGED')
    builder._changed(built['source'],old['commit'],built['commit'],built['allowed_delta'])
    selected = dict(schema=ACCESS_PATH_SCHEMA if bootstrap else
                          SUCCESSOR_SCHEMA if handoff_mode=='POST_TRADE_SUCCESSOR' else SCHEMA,
        operation_id=operation_id,handoff_mode=handoff_mode,
        source=built['source'],deployment=built['deployment'],predecessor=old,
        candidate=dict(commit=built['commit'],image=built['image'],source_identity=built['source_identity']),
        qualification=dict(report_path=qualified['report_path'],report_sha256=qualified['report_sha256'],
            commit=report['commit'],passed=True,source_files=report['source_files']),
        allowed_delta=built['allowed_delta'],created_at=utcnow().isoformat())
    if bootstrap:
        selected['canonical_proof_phase'] = POST_SCHEMA_ACCESS_PATH
    request = validate_request(selected)
    if external:
        write_new(folder/'build-reference.json',dict(schema=builder.BUILD_REFERENCE_SCHEMA,
            path=str(Path(build_record).resolve()),sha256=build_sha256,request_sha256=digest(request)))
    host_type(request,folder).verify_candidate()
    require(builder.pinned_build(build_record,build_sha256) == built, 'BUILD_RECORD_CHANGED')
    write_new(folder/'request.json',request)
    return Journal(folder)


def status(operation_dir):
    journal = Journal(builder.safe_directory(operation_dir))
    receipt = journal.read()
    abandoned=journal.abandonment()
    return dict(operation_id=journal.request['operation_id'],stage=receipt['stage'],
        request_sha256=receipt['request_sha256'],completed_stages=len(receipt['history']),
        last_stage_at=receipt['history'][-1]['at'] if receipt['history'] else None,
        predecessor={key:journal.request['predecessor'][key] for key in ('commit','image')},
        candidate={key:journal.request['candidate'][key] for key in ('commit','image')},
        receipt=str(journal.folder/'receipt.json'),
        **({'abandoned':True,'abandonment_phase':abandoned['phase'],
            'installation_may_resume':False} if abandoned else {}),
        **({'canonical_proof_phase':POST_SCHEMA_ACCESS_PATH}
           if journal.request['schema']==ACCESS_PATH_SCHEMA else {}),
        **({'handoff_mode':'BLOCKED_UNSENT','operational_ready':False,
            'installation_scope':'FENCED_BLOCKED_UNSENT_SOFTWARE_ONLY'}
           if handoff_mode(journal.request)=='BLOCKED_UNSENT' else {}))


def parser(*, backed=False):
    selected = argparse.ArgumentParser(description=__doc__)
    commands = selected.add_subparsers(dest='command',required=True)
    build = commands.add_parser('build',help='Build one exact qualified source layer offline')
    for name in ('source','deployment','predecessor-receipt','qualification','qualification-sha256',
                 'allowed-delta','allowed-delta-sha256','operation-dir','commit'):
        build.add_argument('--'+name,required=True)
    if backed:
        build.add_argument('--allow-started-predecessor',action='store_true')
        build.add_argument('--handoff-mode',choices=('PRE_OPEN','POST_TRADE','BLOCKED_UNSENT','POST_TRADE_SUCCESSOR'),default='PRE_OPEN')
    new = commands.add_parser('prepare',help='Create an immutable operation from its completed build')
    for name in ('operation-dir','build-record','build-sha256','operation-id'):
        new.add_argument('--'+name,required=True)
    new.add_argument('--handoff-mode',choices=('PRE_OPEN','POST_TRADE','BLOCKED_UNSENT','POST_TRADE_SUCCESSOR'),default='PRE_OPEN')
    if backed:
        new.add_argument('--canonical-proof-phase',choices=('PRE_DRAIN',POST_SCHEMA_ACCESS_PATH),
            default='PRE_DRAIN',help='Select the explicit verified-predecessor access-path bootstrap')
    view = commands.add_parser('status',help='Inspect the digest-linked receipt without host operations')
    view.add_argument('--operation-dir',required=True)
    abandon = commands.add_parser('abandon-drain',
        help='Permanently abandon a pre-install operation and recover its exact predecessor restart policy')
    abandon.add_argument('--operation-dir',required=True)
    if backed:
        recovery = commands.add_parser('recover-verification',
            help='Explicit fresh final observation of an expired backed PRE_OPEN installation')
        recovery.add_argument('--operation-dir', required=True)
        recovery.add_argument('--recovery-id', required=True)
    for command in ('advance','resume'):
        proceed = commands.add_parser(command,help='Continue only the next supported delivery stages')
        proceed.add_argument('--operation-dir',required=True)
        proceed.add_argument('--one-stage',action='store_true',help='Stop after one durable stage')
    return selected


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'build':
            record = builder.build(source=args.source,deployment=args.deployment,
                predecessor_receipt=args.predecessor_receipt,qualification=args.qualification,
                qualification_sha256=args.qualification_sha256,
                approved_delta=args.allowed_delta,approved_delta_sha256=args.allowed_delta_sha256,
                operation_dir=args.operation_dir,commit=args.commit)
            output = dict(commit=record['commit'],image=record['image'],
                build_record=str(Path(args.operation_dir)/'build.json'),
                build_sha256=sha256_file(Path(args.operation_dir)/'build.json'))
        elif args.command == 'prepare':
            prepare(operation_dir=args.operation_dir,build_record=args.build_record,
                build_sha256=args.build_sha256,operation_id=args.operation_id,handoff_mode=args.handoff_mode)
            output = status(args.operation_dir)
        elif args.command == 'status':
            output = status(args.operation_dir)
        else:
            journal = Journal(builder.safe_directory(args.operation_dir))
            host = Host(journal.request,journal.folder)
            delivery = Delivery(host,journal)
            if args.command=='abandon-drain':
                delivery.abandon_drain()
            elif args.one_stage:
                with host.owned():
                    delivery.step()
            else:
                delivery.advance()
            output = status(args.operation_dir)
        print(json.dumps(output,sort_keys=True))
        return 0
    except DeliveryRefused as exc:
        print('Local PAPER delivery refused: '+str(exc),file=sys.stderr)
        return 2
    except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired):
        # Expanded input/provider errors can include private configuration.
        print('Local PAPER delivery refused: INVALID_OR_UNREADABLE_INPUT',file=sys.stderr)
        return 2
