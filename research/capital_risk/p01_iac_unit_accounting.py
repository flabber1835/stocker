"""New-only snapshots reuse the exact qualified whole-ledger evaluator."""
from pathlib import Path

from p01_iac_unit_parent import OUTER,need,sha
import p01_native_resume_accounting as previous

CURSOR_SOURCE='72ae13ea86e14859e5af56b74f11c0fbc7b42f07a50e777f38efaf4c2f0298f1'


class AccountingCursor(previous.AccountingCursor):
    """Bind the admitted628 ledger prefix without resetting its cash origin."""
    def __init__(self,parent,quote,actions,*,evaluator=None):
        need(sha(Path(previous.__file__).read_bytes())==CURSOR_SOURCE,
             'EXACT_QUALIFIED_WHOLE_LEDGER_CURSOR_SOURCE')
        need(parent['sha256']==OUTER and parent['completed']==628
             and parent['source_cursor']=='2020-06-30',
             'ACCOUNTING_STARTS_ONLY_AT_ADMITTED628')
        super().__init__(parent,quote,actions,evaluator=evaluator)

    def result(self):
        return dict(super().result(),admitted_parent_outer_sha256=OUTER,
            admitted_parent_completed=628,input_zero_resets_numerical_origin=False)
