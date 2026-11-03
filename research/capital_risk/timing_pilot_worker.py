"""Normal frozen canonical entrypoint with clock-only profiling, hosted use only."""
import os
from pathlib import Path
import runpy
import sys

from timing_observer import TimingObserver


def canonical_arguments():
    return ['research.pooled_vacancy_funding.backtest',
        '--policy','wealth-core-v5-zero-share-fixed-2008-v1',
        '--bundle','/frozen/bundle','--archive','/frozen/archive/corpus.zip',
        '--previous','/frozen/references/owned55','--compact','/frozen/references/compact/champion-daily.csv',
        '--output','/out/run-001','--max-transitions','5','--resume','--checkpoint','/out/run-001/checkpoint.json.gz']


def main():
    if not str(Path(__file__).resolve()).startswith('/driver/'):
        raise ValueError('REFUSED_NONHOSTED_TIMING_WORKER')
    if os.environ.get('CAPITAL_RISK_WINDOW')!='stress-2021':
        raise ValueError('REFUSED_TIMING_WINDOW')
    with Path('/out/pilot-timings.jsonl').open('x',encoding='utf8') as stream:
        observer=TimingObserver(stream);previous=sys.getprofile();sys.argv=canonical_arguments()
        sys.setprofile(observer)
        try:runpy.run_module('research.pooled_vacancy_funding.backtest',run_name='__main__')
        finally:
            sys.setprofile(previous);stream.flush();os.fsync(stream.fileno())


if __name__=='__main__':main()
