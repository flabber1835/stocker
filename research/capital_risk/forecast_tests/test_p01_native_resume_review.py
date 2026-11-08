"""New suffix metadata/arithmetic only; no canonical runtime execution."""
import ast
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import pytest

HERE = Path(__file__).parents[1]
sys.path.insert(0, str(HERE))
import core_window_review as ordinary
import p01_factual_batch_accounting as qualified
import p01_native_resume_accounting as accounting
import p01_native_resume_review as review


def parent():
    return dict(completed=627, source_cursor='2020-06-29', chain='ACTUAL_ADMITTED_CHAIN',
        base={'policy':'SYNTHETIC', 'sources':{'fixed':'fixed'}}, repairs=[{'id':i} for i in range(11)],
        run=dict(input_sha256='53c3b13673552dbf98263ab0272ac11c8951de619bf19e9ddf2020e59b01584a',
                 state=dict(last_processed_session='2020-06-29', ledger={'events':[]})))


def commitment(raw):
    return dict(bytes=len(raw),prefix_sha256=review.sha(raw),
                last_record_sha256=review.sha(raw.splitlines(keepends=True)[-1]) if raw else None)


def test_no_new_source_input_or_descriptor_identity():
    p=parent(); c=deepcopy(p);c.update(completed=628,source_cursor='2020-06-30')
    review.same_resume_identity(p,c)
    for change in ('input','source','descriptor'):
        bad=deepcopy(c)
        if change=='input':bad['run']['input_sha256']='changed'
        if change=='source':bad['base']['sources']['fixed']='changed'
        if change=='descriptor':bad['repairs'][10]={'id':'relabelled'}
        with pytest.raises(ValueError,match='UNCHANGED'):review.same_resume_identity(p,bad)


def test_all_old_raw_prefixes_and_partial_tail_retained():
    before=b'{"session":"old"}\n';new=b'{"session":"new"}\n';tail=b'{"partial":'
    p={'journals':{n:commitment(before) for n in ('daily','formation','monthly','watch')}}
    c={'journals':{n:commitment(before+new) for n in p['journals']}}
    rows,tails,proofs=review.journal_suffixes(p,c,dict.fromkeys(p['journals'],before),
        dict.fromkeys(p['journals'],before+new+tail))
    assert all(v==[{'session':'new'}] for v in rows.values())
    assert all(v=={'bytes':len(tail),'sha256':review.sha(tail)} for v in tails.values())
    assert proofs['daily']['full_bytes']==len(before+new+tail)
    bad=dict.fromkeys(p['journals'],b'changed'+before+new+tail)
    with pytest.raises(ValueError,match='PREFIX_UNCHANGED'):review.journal_suffixes(p,c,dict.fromkeys(p['journals'],before),bad)


@pytest.mark.parametrize('raw,change',[ (b'{}\n','hash'),(b'{}','end'),(b'{}\n','last') ])
def test_prefix_hash_complete_row_and_last_record_are_separate_guards(raw,change):
    c=commitment(raw)
    if change=='hash':c['prefix_sha256']='wrong'
    if change=='last':c['last_record_sha256']='wrong'
    with pytest.raises(ValueError):review.prefix(raw,c)


def test_known_refusal_attempt_is_preserved_not_promoted():
    rows=[{'session':'2020-06-30'}]
    assert review.committed_attempts([],rows,'2020-06-29','2020-06-30')==rows
    with pytest.raises(ValueError,match='CURSOR_FILTER'):
        review.committed_attempts(rows,rows,'2020-06-29','2020-06-30')
    with pytest.raises(ValueError,match='CURSOR_FILTER'):
        review.committed_attempts(rows,rows+[{'session':'2020-07-01'}],'2020-06-30',None)


def test_old_period_attempt_and_new_watch_boundaries_refuse():
    with pytest.raises(ValueError):review.committed_attempts([], [{'session':'2020-06-29'}],'2020-06-29','2020-06-30')
    old=[{'schema':'pooled-source-boundary/1'},{'schema':'research.pooled-action-successor/1'}]
    assert review.boundary_counts(old,[])['pooled-source-boundary/1']==1
    for row in old:
        with pytest.raises(ValueError,match='NO_NEW_SOURCE_OR_INPUT'):review.boundary_counts(old,[row])


def chain_row(p,seed):
    r=dict(session='2020-06-30',phase='MEASURED',input_sha256=p['run']['input_sha256'],
           state_sha256='STATE',economics={'strict':'whole'})
    r['chain_sha256']=review.digest(dict(previous=seed,session=r['session'],state_sha256=r['state_sha256'],economics=r['economics']))
    return r


def test_parent_chain_is_the_only_origin_and_actual_removed_seed_falsifier():
    p=parent();r=chain_row(p,p['chain']);c={'chain':r['chain_sha256']}
    assert review.financial_chain(p,[r],c)==c['chain']
    wrong=chain_row(p,None)
    with pytest.raises(ValueError,match='EXACT_PARENT_CHAIN'):review.financial_chain(p,[wrong],{'chain':wrong['chain_sha256']})
    tree=ast.parse((HERE/'p01_native_resume_review.py').read_bytes())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='financial_chain')
    assert ast.unparse(fn.body[0].value)=="parent['chain']"
    fn.body[0].value=ast.Constant(None);ns=dict(vars(review))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-real-parent-chain>','exec'),ns)
    assert ns['financial_chain'](p,[wrong],{'chain':wrong['chain_sha256']})==wrong['chain_sha256']


def test_gzip_proof_reading_is_explicit_from_producer_filename(tmp_path):
    p=tmp_path/'actual-three-session-component.json.gz';p.write_bytes(gzip.compress(b'{"actual_components":[]}\n',mtime=0))
    assert review.read(p)=={'actual_components':[]}
    p=tmp_path/'ordinary.json';p.write_bytes(gzip.compress(b'{}',mtime=0))
    with pytest.raises((UnicodeDecodeError,ValueError)):review.read(p)


def path_records(p):
    prev=p['run'];rows=[]
    for day in ('2020-06-30',):
        cp=deepcopy(prev);cp['state']['last_processed_session']=day
        rows.append(dict(session=day,prior_checkpoint=deepcopy(prev),publication={'session':day,'entire':'data'},checkpoint=cp))
        prev=cp
    return rows


def test_entire_one_day_qualification_equals_fresh_finance_including_refused_attempt():
    p=parent();path=path_records(p);q=dict(actual_components=path,financial_authority=False)
    f=dict(actual_components=[],attempted_components=path,financial_authority=False,qualification_state_adopted=False)
    c=dict(completed=627,source_cursor='2020-06-29')
    assert review.first_one(p,q,f,c,'2020-06-30')==path
    f['actual_components']=path;c=dict(completed=628,source_cursor='2020-06-30')
    assert review.first_one(p,q,f,c,None)==[]
    bad=deepcopy(f);bad['attempted_components'][0]['publication']['entire']='excluded?'
    with pytest.raises(ValueError,match='NO_FIELD_EXCLUSIONS'):review.first_one(p,q,bad,c,None)


def event(kind,quantity,price,before,delta,detail=None):
    return dict(event_type=kind,security_id='S',session='2020-06-30',shares_delta=quantity,price=price,
        fees=abs(quantity)*price*.001 if kind in ('BUY','SELL') else 0,cash_before=before,cash_delta=delta,
        cash_after=before+delta,detail=detail or {})


def synthetic_snapshots():
    buy=event('BUY',2,10.,50000.,-20.02)
    cash=buy['cash_after'];old=[buy]
    p={'run':{'state':{'ledger':{'events':deepcopy(old)},'wealth_core':{'cash':cash,'episodes':{'1':{'security_id':'S','current_shares':2}}}}}}
    accrue=event('DIVIDEND_ACCRUED',0,1.,cash,0,{'amount':2.,'shares':2})
    first=dict(wealth_core=deepcopy(p['run']['state']['wealth_core']),prices={'S':{'raw_price':11.,'status':'CURRENT'}},
        ledger={'events':old+[accrue],'receivables':[{'security_id':'S','accrued_session':'2020-06-30','amount':2.}]},
        resolved_equity=cash+22+2)
    paid=event('DIVIDEND_PAID',0,1.,cash,2.,{'amount':2.,'accrued_session':'2020-06-30'})
    sale=event('SELL',-1,12.,paid['cash_after'],11.988)
    second=deepcopy(first);second['ledger']={'events':old+[accrue,paid,sale],'receivables':[]}
    second['wealth_core']['cash']=sale['cash_after'];second['wealth_core']['episodes']['1']['current_shares']=1
    second['prices']['S']['raw_price']=12.
    second['resolved_equity']=sale['cash_after']+12
    return p,[first,second]


def test_new_snapshot_adapter_is_exact_existing_full_prefix_evaluator_with_no_old_snapshot_replay():
    p,rows=synthetic_snapshots();called=[]
    def evaluate(snapshot,quote,actions):
        called.append(deepcopy(snapshot));return qualified.reconcile(snapshot,quote,actions)
    cursor=accounting.AccountingCursor(p,{},[],evaluator=evaluate)
    for row in rows:
        before=deepcopy(row);ordinary.reconcile(row)
        expected=qualified.reconcile(row,{},[])
        assert cursor.reconcile(row)==expected and row==before
    assert len(called)==2 and cursor.result()['new_accounting_snapshots']==2
    assert cursor.result()['old_snapshot_replays']==0 and cursor.result()['accounting_origin_reset'] is False


def test_adapter_never_resets_initial_capital_or_numeric_predicates():
    source=(HERE/'p01_native_resume_accounting.py').read_text()
    assert 'self.evaluator(snapshot, self.quote, self.actions)' in source
    assert 'Decimal(' not in source and 'MONEY' not in source and 'round(' not in source
    p,rows=synthetic_snapshots();bad=deepcopy(rows[0]);bad['resolved_equity']+=.001
    with pytest.raises(ValueError,match='RAW_MARK_EQUITY'):accounting.AccountingCursor(p,{},[]).reconcile(bad)
    bad=deepcopy(rows[1]);bad['ledger']['events'][-1]['fees']+=.001
    with pytest.raises(ValueError,match='TRADE_FEE'):accounting.AccountingCursor(p,{},[]).reconcile(bad)


def test_ledger_prefix_guard_removed_actual_falsifier():
    p,rows=synthetic_snapshots();bad=deepcopy(rows[0]);bad['ledger']['events'][0]['reference']='changed-old-metadata'
    with pytest.raises(ValueError,match='PREFIX_UNCHANGED'):
        accounting.AccountingCursor(p,{},[],evaluator=lambda *args:None).reconcile(bad)
    tree=ast.parse((HERE/'p01_native_resume_accounting.py').read_bytes())
    guards=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='need'
        and len(n.args)==2 and isinstance(n.args[1],ast.Constant) and n.args[1].value=='ENTIRE_ADMITTED_AND_NEW_LEDGER_PREFIX_UNCHANGED']
    assert len(guards)==1;guards[0].args[0]=ast.Constant(True);ns={}
    exec(compile(ast.fix_missing_locations(tree),'<removed-prefix-guard>','exec'),ns)
    ns['AccountingCursor'](p,{},[],evaluator=lambda *args:None).reconcile(bad)


def test_adapter_detects_evaluator_mutation():
    p,rows=synthetic_snapshots()
    def mutate(snapshot,*args):snapshot['ledger']['events'][0]['bad']='mutation'
    with pytest.raises(ValueError,match='READ_ONLY'):accounting.AccountingCursor(p,{},[],evaluator=mutate).reconcile(rows[0])


def test_no_top_level_strategy_imports():
    for file in ('p01_native_resume_accounting.py','p01_native_resume_review.py'):
        for node in ast.parse((HERE/file).read_bytes()).body:
            if isinstance(node,ast.ImportFrom):assert not (node.module or '').startswith(('sentinel','stock_strategy_shared','research.pooled'))


def test_only_exact_frozen_qualified_evaluator_dependencies_are_reused():
    request=json.loads((HERE/'p01_factual_batch_request.json').read_bytes())
    for name in ('p01_factual_batch_accounting.py','p01_factual_batch_review.py','core_window_review.py'):
        assert hashlib.sha256((HERE/name).read_bytes()).hexdigest()==request['sources'][name]
    assert ordinary.MONEY==ordinary.D('0.0000001')


def test_new_correlation_preserves_whole_old_prefix_and_exposes_future_tail():
    p=parent();r=chain_row(p,p['chain']);old=b'{"chain_sha256":"OLD"}\n'
    body=dict(session=r['session'],next_state_sha256=r['state_sha256'],input_sha256=r['input_sha256'])
    body['chain_sha256']=review.digest(dict(previous='OLD',record=body))
    raw=(json.dumps(body)+'\n').encode();after=old+raw
    result=review.correlation(old,after,{},'2020-06-29')
    assert result['new_committed_records']==0 and len(result['uncommitted_records'])==1
    assert review.correlation(old,after,{r['session']:r},r['session'])['new_committed_records']==1
    with pytest.raises(ValueError,match='ENTIRE_OLD'):review.correlation(old,b'changed'+after,{r['session']:r},r['session'])
    future=dict(session='2020-07-01',next_state_sha256='future',input_sha256=r['input_sha256'])
    future['chain_sha256']=review.digest(dict(previous=body['chain_sha256'],record=future))
    with pytest.raises(ValueError,match='NO_JULY1'):review.correlation(old,after+(json.dumps(future)+'\n').encode(),{r['session']:r},r['session'])


def source_archive(tmp_path,rows):
    raw='session,security_id,raw_open,raw_close\n'+''.join(','.join(r)+'\n' for r in rows)
    compressed=gzip.compress(raw.encode(),mtime=0);name='observations-2020.csv.gz';path=tmp_path/'frozen.zip'
    with zipfile.ZipFile(path,'w') as z:z.writestr(name,compressed)
    return path,{name:dict(bytes=len(compressed),sha256=review.sha(compressed),rows=len(rows))}


def test_actual_frozen_held_quote_member_hash_rowcount_identity_and_fields(tmp_path):
    path,expected=source_archive(tmp_path,[('2020-06-30','S','12.25','13.5')])
    quotes=[(('2020-06-30','S'),'raw_open',12.25),(('2020-06-30','S'),'raw_close',13.5)]
    assert review.held_quotes(quotes,expected,path)['new_held_raw_quote_checks']==2
    with pytest.raises(ValueError,match='EXACT_NEW_HELD'):review.held_quotes([(quotes[0][0],'raw_open',13.5)],expected,path)
    bad=deepcopy(expected);bad['observations-2020.csv.gz']['sha256']='wrong'
    with pytest.raises(ValueError,match='YEAR_MEMBER_BYTES'):review.held_quotes(quotes,bad,path)
    bad=deepcopy(expected);bad['observations-2020.csv.gz']['rows']=2
    with pytest.raises(ValueError,match='ROW_COUNT'):review.held_quotes(quotes,bad,path)


@pytest.mark.parametrize('rows,reason',[
    ([('2020-06-30','OTHER','12','13')],'PRESENT'),
    ([('2020-06-30','S','12','13'),('2020-06-30','S','12','13')],'UNIQUE')])
def test_frozen_quote_missing_or_duplicated_identity_refuses(tmp_path,rows,reason):
    path,expected=source_archive(tmp_path,rows)
    with pytest.raises(ValueError,match=reason):review.held_quotes([(('2020-06-30','S'),'raw_open',12.)],expected,path)


def test_role_rows_preserve_full_episodes_all_pending_and_selection():
    before=dict(wealth_core={'episodes':{'1':{'security_id':'S','exit_pending':True,'all_fields':'kept'}}},
                pending=[{'security_id':'T','kind':'BUY','full':'intent'}],median5={'selected':['S','T']})
    after=deepcopy(before);after['pending']=[]
    path=[dict(session='2020-06-30',prior_checkpoint={'state':before,'state_sha256':'BEFORE'},
               checkpoint={'state':after,'state_sha256':'AFTER'})]
    got=review.role_rows(path)[0]
    assert got==dict(session='2020-06-30',prior_state_sha256='BEFORE',state_sha256='AFTER',
        before={'episodes':before['wealth_core']['episodes'],'pending':before['pending'],'selected':['S','T']},
        after={'episodes':after['wealth_core']['episodes'],'pending':[],'selected':['S','T']})
    got['before']['episodes']['1']['all_fields']='changed'
    assert before['wealth_core']['episodes']['1']['all_fields']=='kept'
