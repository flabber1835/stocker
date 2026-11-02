"""Exact own41 accurate suffix with one distinct factual/range input."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import digest, sha
from system_campaign_pxd_financial_body import function
from system_campaign_remainder_parent import reference, PATH
from system_campaign_remainder_facts import prepare
from system_campaign_remainder_input import InputCodec
from system_campaign_remainder_sensor import SensorCertificate
from system_campaign_remainder_gate import qualify
from system_campaign_phase_timing import PhaseTiming
from system_campaign_winter2025_cash_context import CashRegistry
import system_campaign_p02_winter2025_cash_run as previous
import system_campaign_p02_unconsumed_cash_run as retained

ECONOMIC = {
    41200949097: 41256802322, '2023-09-29': '2025-04-30', '2023-10-04': '2025-05-16',
    1446: 1842, 34: 41, 992: 1388,
    'RETAINED_SIX_MODEL_Q4_CASH_BATCH_SUFFIX': 'RETAINED_EIGHT_MODELS_AND_REMAINDER_TERMINALS',
    'q4-cash-constructor-admission.json': 'remainder-constructor-admission.json',
    'q4-cash-economic-outcome.json': 'remainder-economic-outcome.json',
    'Q4_CASH_EXACT_OWN_34_INPUT_SEPTEMBER_PARENT': 'REMAINDER_EXACT_STRICT_OWN41_APRIL_PARENT',
    'Q4_CASH_ALL_SIX_ORIGINAL_MODEL_SEMANTICS_UNCHANGED': 'REMAINDER_ALL_EIGHT_ORIGINAL_MODELS_UNCHANGED',
    'Q4_CASH_EXACT_OWN_SUCCESSOR_ALL34_INPUTS_AND_ONE_FACTUAL_CASH_CALENDAR': 'REMAINDER_EXACT_OWN41_AND_ONE_DISTINCT_FACTUAL_INPUT',
    'Q4_CASH_FINANCIAL_REFUSAL_PREFIX_PRESERVED': 'REMAINDER_FINANCIAL_REFUSAL_PREFIX_PRESERVED',
}
WINTER_GATES = ('winter2025-passive-default-canonical-qualification.json',
    'winter2025-positive-cash-canonical-qualification.json', 'winter2025-cash-packet-qualification.json',
    'winter2025-cash-canonical-qualification.json')


def preserve_archives(old, out):
    previous.preserve_archives(old, out)
    for name in WINTER_GATES:
        retained.exact_copy(old / name, out / name)


def economic(out, old, spec, request, timing):
    hosted()
    from research.pooled_vacancy_funding import journal, backtest
    cp = journal.read_checkpoint(old / spec['selected_checkpoint'])
    need(cp['sha256'] == spec['outer_sha256'] and cp['source_cursor'] == '2025-04-30'
         and cp['completed'] == 1842 and len(cp['repairs']) == 41,
         'REMAINDER_NO_DISCOVERY_CHECKPOINT_OR_ROLLBACK')
    facts, parent, refs, path = timing.call('remainder_full_factual_hydration', prepare, cp, old, out, spec)
    codec = InputCodec(out, parent, refs, facts.catalog, facts.natives)
    constructed = []

    def sensor(*args, **kwargs):
        result = SensorCertificate(*args, remainder_codec=codec, remainder_payload=facts.payload, **kwargs)
        constructed.append((args, kwargs, result))
        return result

    def build(current, root, output):
        need(current == cp and root == old and output == out, 'REMAINDER_BUILD_EXACT_PREFLIGHT_PARENT')
        loaded = backtest.load_repair(path, resume_session=current['source_cursor'],
            predecessor_checkpoint_sha256=current['run']['checkpoint_sha256'])
        return facts, loaded, path

    def gate(output, current, material, loaded, objects, selected):
        args, kwargs, actual = constructed[-1]
        gate_out = out / 'remainder-component-qualification'; gate_out.mkdir()
        fixture_kwargs = dict(kwargs)
        fixture_args = (gate_out, *args[1:])
        fixture = SensorCertificate(*fixture_args, remainder_codec=codec,
            remainder_payload=facts.payload, **fixture_kwargs)
        fixture.proof_model = actual.proof_model
        qualify(gate_out, current, material, loaded, objects, selected, codec=codec, certificate=fixture)
        need(not (out / 'uncertainty-certificate.jsonl').exists(),
             'REMAINDER_COMPONENT_PROOF_CANNOT_OVERWRITE_FINANCIAL_CERTIFICATE')
        for cursor, pred in ((cp['source_cursor'], '0' * 64), ('2025-05-16', cp['run']['checkpoint_sha256'])):
            try:
                backtest.load_repair(path, resume_session=cursor, predecessor_checkpoint_sha256=pred)
            except ValueError:
                pass
            else:
                raise ValueError('REFUSED_REMAINDER_WRONG_PREDECESSOR_OR_CONSUMED_SESSION_ACCEPTED')

    namespace = previous.namespace()
    namespace.update(build=build, qualify=gate, SensorCertificate=sensor,
        reference=reference, REFERENCE_PATH=PATH, preserve_all_checkpoints=preserve_archives)
    with codec, retained.retained_scopes(old, cp, out):
        function('system_campaign_p02_q4_cash_run.py', 'economic', ECONOMIC, namespace,
            insert_after='actual_packets_and_own_cash_gate')(out, old, spec, request, timing)


def review(out, root, old, spec, request, timing):
    from system_campaign_remainder_review import review as independent
    return independent(out, root, old, spec, request, timing)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('economic', 'review'), required=True)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    spec, request = json.loads(args.spec.read_bytes()), json.loads(args.request.read_bytes())
    with PhaseTiming(Path('/out'), args.mode) as timing:
        if args.mode == 'economic':
            with CashRegistry():
                economic(Path('/out'), Path('/old'), spec, request, timing)
        else:
            review(Path('/out'), Path('/evidence'), Path('/old'), spec, request, timing)
