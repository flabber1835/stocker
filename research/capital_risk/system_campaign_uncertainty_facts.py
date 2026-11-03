"""Freeze an uncertainty model's factual scope and its exact input evidence."""
from dataclasses import asdict
import json
from pathlib import Path
import zipfile

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import digest, sha

HERE = Path(__file__).resolve().parent
EVIDENCE = (
    ('contract', 'system-campaign-uncertainty-contract.json'),
    ('typed-codec', 'system_campaign_uncertainty_input.py'),
    ('sensor-certificate', 'system_campaign_uncertainty_context.py'),
    ('binary64-proof', 'system_campaign_uncertainty_math.py'),
    ('committed-prefix-reviewer', 'system_campaign_uncertainty_review.py'),
    ('canonical-comparison-adapter', 'system_campaign_uncertainty_gate.py'),
    ('factual-hydration', 'system_campaign_uncertainty_facts.py'),
    ('qualified-synthetic-proof', 'system-campaign-uncertainty-qualification.json'))


def evidence(out):
    result = [dict(reference='research:system-optimization-002/leadership-uncertainty/' + label + '/1',
                   description='Exact research uncertainty contract, implementation or qualified proof.',
                   sha256=sha((HERE / name).read_bytes())) for label, name in EVIDENCE]
    result.append(dict(reference='research:system-optimization-002/leadership-uncertainty/private-event/1',
                       description='Frozen native action and exact event quote/split witness, not a CVR market price.',
                       sha256=sha((out / 'hydrated-uncertainty-event.json').read_bytes())))
    return result


def hydrate(native, out):
    hosted()
    from research.pooled_input_support import inputs
    from research.bounded_20y.run import vendor
    contract = json.loads((HERE / 'system-campaign-uncertainty-contract.json').read_bytes())
    original = json.loads((HERE / 'system-campaign-alder-unresolved-date.json').read_bytes())
    need(digest(asdict(native)) == original['native_term_sha256']
         and contract['session'] == '2019-10-22' and contract['security_id'] == native.security_id,
         'UNCERTAINTY_EXACT_NATIVE_CONTRACT_BINDING')
    found = []
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for row in inputs._archive_rows(archive, 'observations-2019.csv.gz'):
            if row['session'] == contract['session'] and row['security_id'] == native.security_id:
                found.append(row)
    need(len(found) <= 1, 'UNCERTAINTY_UNIQUE_EVENT_SOURCE_QUOTE')
    split = str(vendor(found[0]).split_ratio) if found else '1'
    value = dict(schema='research.leadership-uncertainty-private-event/1',
        session=contract['session'], security_id=native.security_id,
        native_term_sha256=digest(asdict(native)), source_quote_present=bool(found),
        source_quote_row_sha256=digest(found[0]) if found else None, split_ratio=split,
        source_archive='observations-2019.csv.gz', right_market_price_observed=False)
    save(out, value)
    return value


def overlay(cp, root):
    need(cp['source_cursor'] < '2019-10-22', 'UNCERTAINTY_UNCONSUMED_OWN_PREDECESSOR')
    value = dict(schema='research.leadership-uncertainty-input/1',
        predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'], session='2019-10-22',
        security_id='941065113449292610', sensor_only=True, require_unowned_and_unordered=True,
        consideration_range='18<=cash_plus_nontransferable_right<=20',
        treatment='ALL_EXECUTED_COMPARISONS_MUST_BE_INTERVAL_INVARIANT', source_evidence=evidence(root))
    path = root / 'uncertainty-input.json'
    save(path, value)
    return path
