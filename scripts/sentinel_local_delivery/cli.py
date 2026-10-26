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
from .model import (DeliveryRefused, Journal, SCHEMA, read_json, require,
                    utcnow, validate_request, write_new)
from .qualification import sha256_file, validate_report


def prepare(*, operation_dir, build_record, build_sha256, operation_id, host_type=Host,
            baseline_reader=None,handoff_mode='PRE_OPEN'):
    folder = builder.safe_directory(operation_dir)
    require(not (folder/'request.json').exists() and not (folder/'receipt.json').exists(),
            'DELIVERY_OPERATION_ALREADY_PREPARED')
    require(sha256_file(build_record) == build_sha256, 'BUILD_RECORD_CHANGED')
    built = read_json(build_record)
    require(isinstance(built,dict) and set(built) == {
        'schema','at','source','deployment','commit','image','tag','source_identity',
        'strategy_sha256','foundation','predecessor_receipt','qualification','allowed_delta',
        'changed_files','context','log','log_sha256','command'}
        and built['schema'] == builder.BUILD_SCHEMA, 'BUILD_RECORD_SHAPE')
    require(Path(build_record).resolve().parent == folder
        and Path(built['context']).resolve() == folder/'source-context'
        and Path(built['log']).resolve() == folder/'build.log'
        and sha256_file(built['log']) == built['log_sha256'], 'BUILD_ARTIFACTS_CHANGED')
    predecessor = built['predecessor_receipt']
    require(sha256_file(predecessor['path']) == predecessor['sha256'], 'PREDECESSOR_RECEIPT_CHANGED')
    old = (baseline_reader or builder.baseline)(predecessor['path'])
    require(old == built['foundation'], 'BUILD_FOUNDATION_CHANGED')
    qualified = built['qualification']
    report = validate_report(qualified['report_path'],qualified['report_sha256'],built['source'],
        built['commit'],old['commit'])
    require(sorted(built['changed_files']) == built['allowed_delta'], 'BUILD_DELTA_CHANGED')
    builder._changed(built['source'],old['commit'],built['commit'],built['allowed_delta'])
    request = validate_request(dict(schema=SCHEMA,operation_id=operation_id,handoff_mode=handoff_mode,
        source=built['source'],deployment=built['deployment'],predecessor=old,
        candidate=dict(commit=built['commit'],image=built['image'],source_identity=built['source_identity']),
        qualification=dict(report_path=qualified['report_path'],report_sha256=qualified['report_sha256'],
            commit=report['commit'],passed=True,source_files=report['source_files']),
        allowed_delta=built['allowed_delta'],created_at=utcnow().isoformat()))
    host_type(request,folder).verify_candidate()
    write_new(folder/'request.json',request)
    return Journal(folder)


def status(operation_dir):
    journal = Journal(builder.safe_directory(operation_dir))
    receipt = journal.read()
    return dict(operation_id=journal.request['operation_id'],stage=receipt['stage'],
        request_sha256=receipt['request_sha256'],completed_stages=len(receipt['history']),
        last_stage_at=receipt['history'][-1]['at'] if receipt['history'] else None,
        predecessor={key:journal.request['predecessor'][key] for key in ('commit','image')},
        candidate={key:journal.request['candidate'][key] for key in ('commit','image')},
        receipt=str(journal.folder/'receipt.json'))


def parser():
    selected = argparse.ArgumentParser(description=__doc__)
    commands = selected.add_subparsers(dest='command',required=True)
    build = commands.add_parser('build',help='Build one exact qualified source layer offline')
    for name in ('source','deployment','predecessor-receipt','qualification','qualification-sha256',
                 'allowed-delta','allowed-delta-sha256','operation-dir','commit'):
        build.add_argument('--'+name,required=True)
    new = commands.add_parser('prepare',help='Create an immutable operation from its completed build')
    for name in ('operation-dir','build-record','build-sha256','operation-id'):
        new.add_argument('--'+name,required=True)
    new.add_argument('--handoff-mode',choices=('PRE_OPEN','POST_TRADE'),default='PRE_OPEN')
    view = commands.add_parser('status',help='Inspect the digest-linked receipt without host operations')
    view.add_argument('--operation-dir',required=True)
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
            if args.one_stage:
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
