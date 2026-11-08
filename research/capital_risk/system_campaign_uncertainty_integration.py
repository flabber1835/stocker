"""Actual own-input successor and synthetic gateway qualification, no replay."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
import signal
from pathlib import Path
from types import SimpleNamespace

from full_system_benchmark import need, save
from full_system_core import arguments, hosted
from system_campaign_facts import sha
from system_campaign_factual_run import preflight, preserve_tails, correlation_seed, SeededObservation
from system_campaign_own_origin import qualify as qualify_origin
from system_campaign_p02_retained_run import idempotent_dispatch
from system_campaign_readonly import review as readonly_review
from system_campaign_uncertainty_facts import hydrate, evidence, overlay
from system_campaign_uncertainty_support import retained
from system_campaign_uncertainty_input import InputCodec
from system_campaign_uncertainty_context import SensorCertificate, SID, DAY, discrete
from system_campaign_uncertainty_gate import certified_recovery
from system_campaign_uncertainty_math import Interval
from system_campaign_uncertainty_review import seed, validate_input_commitment


class AdmissionPause:
    """Use the canonical graceful-pause branch before any session transition."""
    def __enter__(self):
        from research.pooled_vacancy_funding import backtest, runtime
        self.backtest, self.runtime = backtest, runtime
        self.write, self.advance = backtest.write_json, runtime.advance
        self.handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
        self.paused = False;self.calls = 0
        def write(path, value):
            result = self.write(path, value)
            if Path(path).name == 'status.json' and value.get('status') == 'RESUMED':
                need(not self.paused, 'UNCERTAINTY_ONE_ADMISSION_PAUSE')
                handler = signal.getsignal(signal.SIGTERM)
                need(callable(handler) and handler is not self.handlers[signal.SIGTERM],
                     'UNCERTAINTY_ACTUAL_CANONICAL_PAUSE_HANDLER')
                handler(signal.SIGTERM, None);self.paused = True
            return result
        def advance(*args, **kwargs):
            self.calls += 1
            raise ValueError('REFUSED_UNCERTAINTY_QUALIFICATION_MUST_NOT_ADVANCE')
        backtest.write_json, runtime.advance = write, advance
        return self

    def __exit__(self, *args):
        self.backtest.write_json, self.runtime.advance = self.write, self.advance
        for key, value in self.handlers.items():signal.signal(key, value)


def synthesize(out, codec, native, hashes, event_source):
    """Actual qualified functions and journal, synthetic states/identities only."""
    from sentinel.controller import median5, champion_config
    from sentinel.core.session import PublishedSession
    from research.pooled_vacancy_funding import journal
    source_bar = SimpleNamespace(security_id=SID, session=DAY, split_ratio=float(event_source['split_ratio']))
    published = PublishedSession(session=DAY, data_version=1,
        bars=[source_bar] if event_source['source_quote_present'] else [], meta={}, sectors={}, spy_closeadj=[],
        terminal_events=(replace(native, session=DAY),))
    state = median5.fresh(champion=True)
    state.update(last_session='2019-10-21', witness_nav=[1.02 ** n for n in range(41)],
                 selected=[SID, 'SYNTHETIC-OTHER'], selected_closes={SID:20., 'SYNTHETIC-OTHER':100.})
    prior = SimpleNamespace(wealth_core={'episodes':{}}, pending=[], median5=state,
        last_processed_session='2019-10-21', feed={'series':{SID:{'signal_basis_anchor':['2019-10-21',20.,20.]}}})
    first = out / 'synthetic-certificate-first';first.mkdir();(first / 'book').mkdir()
    with SensorCertificate(first, codec, native, hashes, event_source=event_source) as certificate:
        prices = {'SYNTHETIC-OTHER':102.}
        values = certificate.values(prior=prior, published=published)
        need(values[SID] == float(18 * Fraction(event_source['split_ratio'])),
             'UNCERTAINTY_ACTUAL_SYNTHETIC_GATEWAY_REPRESENTATIVE')
        for owned in (True, False):
            bad = deepcopy(prior)
            if owned:bad.wealth_core['episodes']['0'] = {'security_id':SID}
            else:bad.pending = [{'security_id':SID}]
            try:certificate.values(prior=bad, published=published)
            except ValueError as exc:need('CVR_MUST_NOT_BE_' in str(exc), 'UNCERTAINTY_ACTUAL_OWNED_ORDERED_REFUSAL')
            else:raise ValueError('REFUSED_UNCERTAINTY_OWNED_OR_ORDERED_GUARD')
        values = certificate.values(prior=prior, published=published)
        changed = replace(published, terminal_events=(replace(native, session=DAY, cash_per_share=18.),))
        try:certificate.values(prior=prior, published=changed)
        except ValueError as exc:need('EXACT_UNRESOLVED_SOURCE_TERM' in str(exc), 'UNCERTAINTY_ACTUAL_INCOMPLETE_TERM_GUARD')
        else:raise ValueError('REFUSED_UNCERTAINTY_COMPLETE_CASH_TERM_REJECTED')
        values = certificate.values(prior=prior, published=published)
        state, observed = median5.witness(state, session=DAY,
            candidates=[SimpleNamespace(security_id='SYNTHETIC-OTHER',recent=1.)], closes=prices,
            terminals={SID}, terminal_values=values)
        state, decision = champion_config.recover(state=state,native=1.,wc_drawdown=-.05,
            spy_r20=.02,wc_r20=.01,**observed)
        certificate.pending.update(input_sha256='a'*64,prior_state_sha256='b'*64,next_state_sha256='c'*64)
        j = journal.Journal(first / 'book')
        try:
            j.append('daily',dict(session=DAY,state_sha256='c'*64,input_sha256='a'*64))
            commitment = j.commitment()
        finally:j.close()
    synthetic_cp = dict(source_cursor=DAY,journals=commitment)
    admitted = seed(first, synthetic_cp)
    need(len(admitted) == 1, 'UNCERTAINTY_ACTUAL_JOURNAL_BOUND_CERTIFICATE_PREFIX')
    second = out / 'synthetic-certificate-resume';second.mkdir();(second / 'book').mkdir()
    for name in ('formation','daily','monthly','watch'):
        (second / 'book' / (name+'.jsonl')).write_bytes((first / 'book' / (name+'.jsonl')).read_bytes())
    with SensorCertificate(second,codec,native,hashes,seed=admitted,event_source=event_source) as certificate:
        state, observed = median5.witness(state,session='2019-10-23',
            candidates=[SimpleNamespace(security_id='SYNTHETIC-OTHER',recent=1.)],
            closes={'SYNTHETIC-OTHER':104.04},terminals=set(),terminal_values={})
        state, decision = champion_config.recover(state=state,native=1.,wc_drawdown=-.05,
            spy_r20=.02,wc_r20=.01,**observed)
        certificate.pending.update(input_sha256='a'*64,prior_state_sha256='c'*64,next_state_sha256='d'*64)
        j = journal.Journal(second / 'book',resume=True)
        try:
            j.recover(commitment)
            j.append('daily',dict(session='2019-10-23',state_sha256='d'*64,input_sha256='a'*64))
            second_commitment = j.commitment()
        finally:j.close()
    need(len(seed(second,dict(source_cursor='2019-10-23',journals=second_commitment))) == 2,
         'UNCERTAINTY_ACTUAL_FULL_CERTIFICATE_RESTART')
    # Cover every uncertain comparison used by the actual frozen recovery:
    # r20>0, r40>-.04, r20>=Core20 and r20<=-.085, including episode/latch paths.
    cases = []
    for episode, r20, r40, wc20, wcdd in ((False,-.095,.1,.01,-.11), (True,.02,-.1,.005,-.05)):
        s = median5.fresh(champion=True);s.update(episode=episode,recent_positive_streak=7 if episode else 0)
        (_, decision), checks = certified_recovery(champion_config.recover,
            dict(state=s,native=1.,wc_drawdown=wcdd,spy_r20=.02,wc_r20=wc20,recent_r20=r20,recent_r40=r40),
            {'recent_r20':Interval(r20-.001,r20+.001),'recent_r40':Interval.point(r40)})
        cases.extend(checks)
    need({'gt','ge','le'} <= {v['relation'] for v in cases}, 'UNCERTAINTY_ACTUAL_RECOVERY_BRANCH_COVERAGE')
    try:
        certified_recovery(champion_config.recover,
            dict(state=median5.fresh(champion=True),native=1.,wc_drawdown=-.05,spy_r20=.02,wc_r20=.01,recent_r20=0.,recent_r40=.1),
            {'recent_r20':Interval(-.1,.1),'recent_r40':Interval.point(.1)})
    except ValueError as exc:need('AMBIGUOUS_CONTROLLER_COMPARISON' in str(exc), 'UNCERTAINTY_ACTUAL_AMBIGUITY_REFUSAL')
    else:raise ValueError('REFUSED_UNCERTAINTY_AMBIGUOUS_COMPARISON')
    save(out / 'gateway-integration-qualification.json',dict(status='SYNTHETIC_GATEWAY_AND_JOURNAL_RESTART_PASSED',
        actual_gateway_unowned_and_ordered_guards=True,actual_complete_term_refused=True,
        actual_canonical_comparison_relations=sorted({v['relation'] for v in cases}),
        actual_ambiguous_comparison_refused=True,actual_synthetic_journal_sessions=2,
        historical_financial_sessions_advanced=0,actual_own_financial_state_used_as_synthetic=False))


def run(out, old, spec, request):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal,runtime
    cp = preflight(spec,old,out,before=DAY)
    need(spec['arm']=='P02' and spec['run_id']==41056373429 and cp['source_cursor']=='2019-09-30'
         and cp['completed']==439, 'UNCERTAINTY_EXACT_OWNER_SELECTED_OWN_PREFIX')
    qualify_origin(out,cp,out / 'own-origin-qualification.json')
    v1,spin,alder,_ = retained(cp,old,out)
    event_source = hydrate(alder.native,out / 'hydrated-uncertainty-event.json')
    path = overlay(cp,out);codec = InputCodec(evidence(out))
    rows = correlation_seed(old,cp)
    observer = SeededObservation(out / 'correlation-inputs.jsonl.gz',rows)
    args = arguments(out / 'book',True);args[args.index('--policy')+1] = cp['base']['policy']
    with v1,spin,alder,idempotent_dispatch(alder),codec:
        for cursor, predecessor in ((cp['source_cursor'],'0'*64),(DAY,cp['run']['checkpoint_sha256'])):
            try:backtest.load_repair(path,resume_session=cursor,predecessor_checkpoint_sha256=predecessor)
            except ValueError:pass
            else:raise ValueError('REFUSED_UNCERTAINTY_ACTUAL_INPUT_PREDECESSOR_FALSIFIER')
        loaded = backtest.load_repair(path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
        from research.pooled_input_support.adapter import Packet
        packet = Packet(DAY,(),{},{},1.,{},(),())
        need(backtest.apply_repair(packet,loaded) is packet,'UNCERTAINTY_INPUT_COMMITS_WITHOUT_PACKET_CHANGE')
        synthesize(out,codec,alder.native,request['canonical_controller_sources'],event_source)
        with observer,AdmissionPause() as pause:
            code = backtest.main(args+['--repair-overlay',str(path)])
        need(code == 0 and pause.paused and pause.calls == 0,'UNCERTAINTY_ACTUAL_ZERO_SESSION_CANONICAL_ADMISSION')
        current = journal.read_checkpoint(out / 'book/checkpoint.json.gz')
        for name in ('base','source_cursor','completed','economics','stats','spy_base','retries'):
            need(current[name] == cp[name],'UNCERTAINTY_ALL_PREEXISTING_FINANCIAL_FIELDS_UNCHANGED')
        need(current['run']['state'] == cp['run']['state'] and current['run']['state_sha256'] == cp['run']['state_sha256']
             and current['repairs'][:-1] == cp['repairs'] and current['repairs'][-1]['sha256'] == loaded.sha256
             and current['run']['input_sha256'] == backtest.input_hash(current['base'],current['repairs'])
             and current['run']['input_sha256'] != cp['run']['input_sha256'], 'UNCERTAINTY_EXACT_INPUT_SUCCESSOR_ONLY')
        restored = runtime.restore(current['run'],policy=current['base']['policy'],input_sha256=current['run']['input_sha256'])
        need(runtime.checkpoint(restored) == current['run'],'UNCERTAINTY_NEW_INPUT_CANONICAL_ROUNDTRIP')
        for name in ('formation','daily','monthly'):
            need(current['journals'][name] == cp['journals'][name], 'UNCERTAINTY_OLD_FINANCIAL_PREFIXES_EXACT')
        readonly_review(out / 'book',out / 'core-review.json')
        need(validate_input_commitment(out,current)==loaded.sha256,'UNCERTAINTY_INDEPENDENT_MODEL_COMMITMENT_REVIEW')
    save(out / 'recovered-tail-proof.json',preserve_tails(out / 'book',json.loads((out / 'factual-preflight.json').read_bytes())))
    save(out / 'correlation-capture-proof.json',observer.proof())
    save(out / 'uncertainty-successor-qualification.json',dict(status='OWN_INPUT_SUCCESSOR_QUALIFIED_ZERO_SESSIONS',
        original_outer_sha256=cp['sha256'],candidate_outer_sha256=current['sha256'],
        original_input_sha256=cp['run']['input_sha256'],candidate_input_sha256=current['run']['input_sha256'],
        input_descriptor_sha256=loaded.sha256,selected_session=current['source_cursor'],completed=current['completed'],
        all_financial_controller_reporting_fields_unchanged=True,all_original_financial_prefixes_unchanged=True,
        actual_canonical_pause_before_runtime_advance=True,actual_runtime_advance_calls=0,
        actual_new_input_canonical_roundtrip=True,old_gzip_and_recovered_tails_preserved=True,
        source_conversion=False,new_origin=False,financial_replay_started=False,production_contacted=False))


if __name__ == '__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--spec',type=Path,required=True);p.add_argument('--request',type=Path,required=True)
    a=p.parse_args();run(Path('/out'),Path('/old'),json.loads(a.spec.read_bytes()),json.loads(a.request.read_bytes()))
