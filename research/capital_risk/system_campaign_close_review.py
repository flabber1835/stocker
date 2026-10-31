"""Independent actual eligibility and closing-notional review of stopped evidence."""
from fractions import Fraction
import json

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import sha
from system_campaign_uncertainty_review import committed_rows
from system_campaign_close_scope import SCHEMA, active, require_absent, require_intents, review_guards
from system_campaign_close_facts import contract, PRIVATE
from system_campaign_close_basis import validate


def certificate_for(path, day):
    found = None
    with path.open('rb') as stream:
        for raw in stream:
            value = json.loads(raw)
            if value['session'] != day: continue
            need(found is None, 'CLOSE_REVIEW_NO_DUPLICATE_COMPLETION_CERTIFICATE')
            found = value
    need(found is not None, 'CLOSE_REVIEW_ACTUAL_COMPLETION_CERTIFICATE_REQUIRED')
    return found


def require_closing_notional(certificate, row, sid, anchor, delivered_close, day, native):
    need(anchor[0] == native and row['session'] == day and certificate['session'] == day,
         'CLOSE_REVIEW_ACTUAL_PRIOR_SIGNAL_BASIS_AND_COMPLETION_DATES')
    raw, signal, close = (Fraction(str(v)) for v in (anchor[1], anchor[2], delivered_close))
    need(min(raw, signal, close) > 0, 'CLOSE_REVIEW_POSITIVE_ACTUAL_PRICE_BASIS')
    expected = float((Fraction('30') + Fraction('0.03002') * close) * signal / raw)
    items = [v for v in certificate['material']['rows'] if v['security_id'] == sid]
    need(len(items) == 1, 'CLOSE_REVIEW_UNIQUE_ACTUAL_COMPLETION_MATERIAL')
    need(items[0]['current'] == [expected, expected]
         and certificate['next_state_sha256'] == row['state_sha256']
         and certificate['input_sha256'] == row['input_sha256'],
         'CLOSE_REVIEW_ACTUAL_COMMITTED_EXACT_CLOSING_NOTIONAL')
    return dict(signal_consideration=expected, delivered_raw_close=delivered_close)


def review(root, cp, output):
    hosted()
    from research.pooled_vacancy_funding import journal
    obj, = validate(root, cp);c = contract();event = c['event'];sid = event['security_id'];day = event['session']
    financial = [*committed_rows(root / 'book', cp, 'formation'), *committed_rows(root / 'book', cp, 'daily')]
    watch = committed_rows(root / 'book', cp, 'watch')
    scope = review_guards(financial, watch, guarded_input_sha256=obj.sha256)
    for row in financial:
        if not active(row['session']): continue
        audit = row['evidence']['research_entry_audit']
        for state in (audit['opening_accounting'], audit['closing_accounting']):
            require_absent(state['wealth_core'], state['pending'], [sid])
        require_intents(row['evidence']['wealth_core']['intents'], [sid])
    forbidden = {'BUY', 'SELL', 'CASH_MERGER', 'CONVERSION', 'WRITE_OFF', 'TERMINAL_LIQUIDATION', 'TERMINAL_MARK'}
    events = cp['run']['state']['ledger']['events']
    affected = [v for v in events if v['security_id'] == sid and v['session'] >= event['native_session']
                and v['event_type'] in forbidden]
    need(not affected, 'CLOSE_REVIEW_NO_ACTUAL_SOURCE_TRADE_PAYMENT_OR_DELIVERY')
    actual = None
    if cp['source_cursor'] >= day:
        row, = [v for v in financial if v['session'] == day]
        matches = []
        for path in (root / 'book/pre-event').glob(day + '-*.json.gz'):
            value = journal.read_checkpoint(path)
            if value['run']['input_sha256'] != row['input_sha256']: continue
            proofs = [v for v in watch if v.get('schema') == 'research.guarded-close-conversion-watch/1'
                      and v['session'] == day and v['prior_state_sha256'] == value['run']['state_sha256']]
            if proofs: matches.append((path, value))
        need(len(matches) == 1, 'CLOSE_REVIEW_UNIQUE_ACTUAL_CANONICAL_PRE_EVENT_CHECKPOINT')
        path, predecessor = matches[0];state = predecessor['run']['state']
        need(predecessor['source_cursor'] == event['native_session'], 'CLOSE_REVIEW_EXACT_ACTUAL_LAST_TRADING_PREDECESSOR')
        require_absent(state['wealth_core'], state['pending'], [sid])
        require_intents(state['last_evidence']['wealth_core']['intents'], [sid])
        payload = json.loads((root / PRIVATE).read_bytes())
        delivered, = [v for v in payload['source_witnesses'] if v['security_id'] == event['added']['delivered_security_id']]
        selected = sid in state['median5']['selected']
        material = None
        if selected:
            anchor = state['feed']['series'][sid]['signal_basis_anchor']
            certificate = certificate_for(root / 'uncertainty-certificate.jsonl', day)
            material = require_closing_notional(certificate, row, sid, anchor,
                float(delivered['raw_close']), day, event['native_session'])
        actual = dict(session=day, selected_leadership=selected, exact_notional=material,
            predecessor_path=path.relative_to(root).as_posix(), predecessor_file_sha256=sha(path.read_bytes()),
            predecessor_outer_sha256=predecessor['sha256'], actual_portfolio_cash_or_delivery=False)
    value = dict(status='ACTUAL_GUARDED_CLOSE_WINDOW_REVIEWED', checkpoint_sha256=cp['sha256'],
        through=cp['source_cursor'], scope=scope, actual_completed_event=actual,
        no_owned_lot_settlement_model=True, no_cil_price_selected=True,
        preopen_completion_claimed=False, all_actual_scope_guards_bound=True,
        input_schema=SCHEMA, input_sha256=obj.sha256, production_contacted=False)
    save(output, value)
    return value
