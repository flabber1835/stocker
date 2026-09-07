import pytest
from backtester.production_equivalent_economic_overlay import _dividend_due_lag, assert_contract


def test_exact_lag_parser_distinguishes_one_from_fifteen():
    assert _dividend_due_lag("book.receivables.append((gday+1,q*rawdiv))") == 1
    assert _dividend_due_lag("book.receivables.append((gday+15,q*rawdiv))") == 15


def test_fifteen_session_expression_cannot_pass_contract():
    source = '''\nfrom backtester import champion_final_security_truth as _bestclass\nterm_tids=()\n_leadership_terminal_tids=()\nbook.receivables.append((gday+15,q*rawdiv))\nopen_eq,_=book.equity(opraw)\neq,unresolved=book.equity(clraw)\n'''
    with pytest.raises(RuntimeError, match="dividend lag must be exactly 1 session"):
        assert_contract(source)
