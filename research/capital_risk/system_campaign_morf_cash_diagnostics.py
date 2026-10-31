"""Original stopped-only diagnostic fences, with the explicit MORF entrypoint."""
import argparse
from pathlib import Path
import system_campaign_p02_close_diagnostics as original
from system_campaign_pxd_financial_body import function


def stopped(inspection,metadata,role,run_id,request_name):
    return function('system_campaign_p02_close_diagnostics.py','stopped',{
        '/driver/system_campaign_p02_close_run.py':'/driver/system_campaign_p02_morf_cash_run.py'},
        vars(original))(inspection,metadata,role,run_id,request_name)


def main(args):
    return function('system_campaign_p02_close_diagnostics.py','main',{
        'p02-close-financial-output':'p02-morf-cash-output'},
        dict(vars(original),stopped=stopped,__file__=__file__))(args)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('request','receipt','output'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
