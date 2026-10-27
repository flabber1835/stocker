"""Actual bounded packet boundary checks, without a portfolio transition."""
import argparse
from dataclasses import asdict
import hashlib
import itertools
import json
from pathlib import Path
import zipfile


def run(bundle,archive,start,end,output):
    from research.pooled_input_support import inputs
    from research.pooled_input_support.adapter import Packet
    from research.pooled_input_support.bundle import axis,verify_bundle
    from research.economic_replay60.inputs import Classification
    from research.bounded_20y.run import metadata,vendor,distributions
    full=axis();first=full[full.index(start)-425]
    manifest=verify_bundle(bundle,archive_override=archive)
    overlay={(r['session'],r['security_id']):r for r in json.loads((bundle/'spinoff-proxy-overlay.json').read_bytes())}
    actions=inputs.load_actions(bundle)
    benchmark={r['session']:float(r['level']) for r in inputs._gzip_rows(bundle/'benchmark.csv.gz')}
    cash={r['session']:r for r in inputs._gzip_rows(bundle/'cash.csv.gz')}
    proof=[]
    with zipfile.ZipFile(archive) as zipped:
        spins=distributions(inputs._archive_rows(zipped,'actions.csv.gz'))
        for day,reviewed in actions.spins.items():
            parents={r.parent_security_id for r in reviewed}
            spins[day]=[r for r in spins.get(day,()) if r.parent_security_id not in parents]+reviewed
        for day in (first,start,end):
            partition,=[p for p in manifest['observation_partitions'] if p['year']==int(day[:4])]
            source=(inputs._gzip_rows(bundle/partition['path']) if 'path' in partition else
                inputs._archive_rows(zipped,partition['archive_member']))
            classifier=Classification();expected=None
            for observed,group in itertools.groupby(source,lambda r:r['session']):
                if observed<day:continue
                if observed>day:break
                bars,meta,sectors=[],{},{}
                for raw in group:
                    raw=overlay.get((day,raw['security_id']),raw)
                    row=classifier.apply(raw);sid=row['security_id']
                    bars.append(vendor(row));meta[sid]=metadata(row);sectors[sid]=row['ff12'] or None
                expected=Packet(day,tuple(bars),meta,sectors,benchmark[day],cash[day],
                    tuple(actions.terminal.get(day,())),tuple(spins.get(day,())))
                break
            actual=list(inputs.packets(bundle,archive,first=day,last=day))
            if expected is None or len(actual)!=1 or asdict(expected)!=asdict(actual[0]):
                raise ValueError('REFUSED_BOUNDED_PACKET_EQUIVALENCE_'+day)
            payload=json.dumps(asdict(expected),sort_keys=True,default=str,allow_nan=False).encode()
            proof.append(dict(session=day,securities=len(expected.bars),packet_sha256=hashlib.sha256(payload).hexdigest()))
    output.write_text(json.dumps(dict(status='BOUNDED_INPUT_BOUNDARIES_MATCHED',samples=proof,
        first=first,start=start,end=end,portfolio_transitions=0),indent=2)+'\n')
    print('BOUNDED_INPUT_BOUNDARIES_MATCHED')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('bundle','archive','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--start',required=True);p.add_argument('--end',required=True);a=p.parse_args()
    run(a.bundle,a.archive,a.start,a.end,a.output)
