"""Read-only observations of the canonical book, never an accounting engine."""
from copy import deepcopy


def snapshot(state,ledger,pending,prices,*,session,phase,resolved_equity):
    return deepcopy(dict(schema='research.capital-risk-core-accounting/1',session=session,
        phase=phase,resolved_equity=resolved_equity,wealth_core=state.to_dict(),
        ledger=ledger.to_dict(),pending=[p.to_dict() for p in pending],prices=prices))
