"""Metadata-only exact431 inheritance, indexed parents and request closure."""
import argparse
import json
from pathlib import Path
from system_campaign_discovery_suffix_probe import Fence

def main(args):
 from system_campaign_discovery_indexed_spinoff_job import expected_request
 from full_system_benchmark import need
 value=expected_request();need(json.loads(args.request.read_bytes())==value,'INDEXED_SPIN_EXACT_METADATA_REQUEST')
 print(json.dumps(dict(status='INDEXED_SPIN_METADATA_ONLY_VERIFIED',sources=len(value['sources']),retained_sources=431,
  arms=value['arms'],indexed_seed_counts=value['seed_counts'],financial_authority=False,
  local_canonical_execution=False,production_contacted=False)),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);main(p.parse_args())
