"""Run isolated deliberate defects against the research falsifiers."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


CASES = (
    ('hide_ineligible_held_exit','account.py',
     "or b.eligibility_reason=='SNAPSHOT_INELIGIBLE'",'or False',
     'test_account.py::test_failed_entry_filter_does_not_hide_valid_held_exit[volume-1.0]'),
    ('duplicate_correction','policy.py','if key in seen:','if False:',
     'test_policy.py::test_corrections_are_atomic_and_window_bounded[duplicate]'),
    ('correction_horizon','policy.py','if not lower <= series.session_indices[pos] <= feed._session_index:',
     'if False:','test_policy.py::test_corrections_are_atomic_and_window_bounded[old]'),
    ('immortal_peak','policy.py',"for i,c in prior['observations'] if i >= lower",
     "for i,c in prior['observations']",'test_policy.py::test_rolling_peak_expires_on_market_session_300'),
    ('lost_reference_rebase','policy.py','rows = [[i, c*factor]',
     'rows = [[i, c]','test_policy.py::test_corporate_reference_rebase_does_not_create_stop'),
    ('ignore_buy_reservation','account.py','account.cash-account.reserved_cash','account.cash',
     'test_account.py::test_no_spending_pending_sale_or_reserved_buy_cash'),
    ('ignore_pending_order','account.py','sid in account.positions or sid in account.pending or sid in veto',
     'sid in account.positions or sid in veto','test_account.py::test_no_spending_pending_sale_or_reserved_buy_cash'),
    ('ignore_terminal_veto','account.py','or sid in veto','or False',
     'test_account.py::test_terminal_veto_and_stop_prevent_reentry'),
)


def run():
    root=Path(__file__).resolve().parents[2]
    outcomes=[]
    for name,file,old,new,test in CASES:
        with tempfile.TemporaryDirectory(prefix='data-available-mutation-') as directory:
            temporary=Path(directory)
            package=temporary/'research/data_available'
            shutil.copytree(Path(__file__).parent,package,ignore=shutil.ignore_patterns('__pycache__'))
            path=package/file
            source=path.read_text()
            if source.count(old)!=1:
                raise ValueError('mutation target changed: '+name)
            path.write_text(source.replace(old,new))
            env={**os.environ,'PYTHONPATH':os.pathsep.join((str(temporary),str(root),str(root/'shared')))}
            completed=subprocess.run([sys.executable,'-m','pytest',str(package/test),'-q',
                '-p','no:cacheprovider','--tb=short'],cwd=temporary,env=env,
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=90)
            killed=(completed.returncode==1 and '1 failed' in completed.stdout
                    and ('AssertionError' in completed.stdout or 'DID NOT RAISE' in completed.stdout))
            row=dict(mutation=name,killed=killed,test=test)
            outcomes.append(row)
            print(json.dumps(row),flush=True)
            if not killed:
                print(completed.stdout)
                raise RuntimeError('mutation not behaviorally killed: '+name)
    return outcomes


if __name__=='__main__':
    run()
