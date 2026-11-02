"""Same canonical P10 worker, explicit flattened-driver request API."""
import argparse
from pathlib import Path
from system_campaign_p10_ahl2_context import worker_namespace

def main(args):return worker_namespace()['main'](args)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=('qualify','discovery','review'),required=True)
    for name in ('spec','request'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
