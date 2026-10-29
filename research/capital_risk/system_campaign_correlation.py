"""Causal residual-peer classifier compilation and exact shared calculations."""
import ast,hashlib,os,struct,types
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from system_campaign_joint_space import correlation_record,DEFAULT_CORRELATION
from full_system_benchmark import need


def decode(value):
    if isinstance(value,dict):
        if set(value)=={'ieee754_binary64'}:
            raw=bytes.fromhex(value['ieee754_binary64']);need(len(raw)==8,'CORRELATION_NONFINITE_ENCODING')
            number=struct.unpack('>d',raw)[0];need(not np.isfinite(number),'CORRELATION_EXPLICIT_NONFINITE_ONLY');return number
        return {k:decode(v) for k,v in value.items()}
    if isinstance(value,list):return [decode(v) for v in value]
    return value


def render(raw,parameters,expected_sha):
    p=correlation_record(parameters)['parameters']
    need(hashlib.sha256(raw).hexdigest()==expected_sha,'CORRELATION_FROZEN_SOURCE')
    text=raw.decode()
    for old,new,count in (
        ('index-252',f'index-{p["lookback"]}',1),('len(keys) < 120',f'len(keys) < {p["minimum_observations"]}',1),
        ('len(common) < 120',f'len(common) < {p["minimum_observations"]}',1),
        ('c >= 0.145',f'c >= {p["cutoff"]!r}',1),('scores[:3]',f'scores[:{p["neighbors"]}]',1),
        ('h.own_dd <= -0.10',f'h.own_dd <= {p["own_dd"]!r}',1),
        ('h.r21 <= -0.03',f'h.r21 <= {p["r21"]!r}',1),('stress >= 0.5',f'stress >= {p["stress"]!r}',1)):
        need(text.count(old)==count,'CORRELATION_PARAMETER_SITE:'+old);text=text.replace(old,new)
    tree=ast.parse(text);function,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='breadth']
    start,=[i for i,n in enumerate(function.body) if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Tuple)
             and [v.id for v in n.targets[0].elts]==['greens','reds']]
    prefix=ast.parse('''market = {int(r[0]): r[2] for r in material['spy_history']}
index = material['index']
held = [Holding(**r['canonical_holding']) for r in material['held']]
identities = [tuple(r['peer_key']) for r in material['held']]
residuals = [_residuals(SimpleNamespace(session_indices=r['session_indices'], signal_closes=r['signal_closes']), index, market) for r in material['held']]
''').body
    function.name='from_capture';function.args=ast.arguments(posonlyargs=[],args=[ast.arg(arg='material')],kwonlyargs=[],kw_defaults=[],defaults=[])
    function.body=prefix+function.body[start:]
    result=(ast.unparse(ast.fix_missing_locations(tree))+'\n').encode();ast.parse(result)
    return result


def module(raw,parameters,expected_sha):
    need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
         and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_CORRELATION_ONLY')
    compiled=render(raw,parameters,expected_sha);value=types.ModuleType('_private_campaign_correlation_'+correlation_record(parameters)['id'])
    value.SimpleNamespace=SimpleNamespace;exec(compile(compiled,'<private-canonical-correlation-classifier>','exec'),value.__dict__)
    value.compiled_sha256=hashlib.sha256(compiled).hexdigest();return value


def threshold_batch(holdings,greens,stress,profiles):
    """Only independent Boolean/fraction arithmetic; inputs may be synthetic."""
    n=len(holdings);count=len(profiles)
    need(np.shape(stress)==(count,n) and len(greens)==n,'CORRELATION_BATCH_SHAPES')
    if not n:return np.zeros(count),np.zeros(count,dtype=np.int64),np.zeros((count,0),dtype=bool)
    own=np.asarray([h.own_dd if h.own_dd is not None else np.nan for h in holdings],float)
    r21=np.asarray([h.r21 if h.r21 is not None else np.nan for h in holdings],float)
    dd=np.asarray([p['own_dd'] for p in profiles],float)[:,None]
    r=np.asarray([p['r21'] for p in profiles],float)[:,None]
    escalation=np.asarray([p['stress'] for p in profiles],float)[:,None]
    individual=(np.isfinite(own)&(own<=dd))|(np.isfinite(r21)&(r21<=r))
    amber=individual|((stress>=escalation)&~np.asarray(greens,bool)[None,:])
    counts=amber.sum(axis=1,dtype=np.int64)
    return counts/n,counts,amber


class ClassifierBatch:
    def __init__(self,raw,expected_sha,profiles):
        self.profiles=[correlation_record(p)['parameters'] for p in profiles]
        self.modules={}
        for p in self.profiles:
            key=p['lookback'],p['minimum_observations']
            if key not in self.modules:self.modules[key]=module(raw,{**DEFAULT_CORRELATION,'lookback':key[0],'minimum_observations':key[1]},expected_sha)
        self.default=self.modules[(252,120)]

    def one(self,material):
        material=decode(material);index=material['index'];records=material['held']
        held=[self.default.Holding(**r['canonical_holding']) for r in records]
        greens=[self.default.is_green(h) for h in held];reds=[self.default.is_red(h) for h in held]
        keys=[tuple(r['peer_key']) for r in records];n=len(held);market={int(r[0]):r[2] for r in material['spy_history']}
        need(len({r['slot'] for r in records})==n,'CORRELATION_UNIQUE_CANONICAL_SLOTS')
        histories=[SimpleNamespace(session_indices=r['session_indices'],signal_closes=r['signal_closes']) for r in records]
        cache={}
        for key,implementation in self.modules.items():
            residuals=[implementation._residuals(s,index,market) for s in histories]
            scores=[]
            for i in range(n):
                values=[]
                for j in range(n):
                    if i==j:continue
                    c=implementation._correlation(residuals[i],residuals[j])
                    if c is not None:values.append((c,keys[j],j))
                values.sort(key=lambda r:(-r[0],r[1]));scores.append(values)
            for cutoff,neighbors in {(p['cutoff'],p['neighbors']) for p in self.profiles if (p['lookback'],p['minimum_observations'])==key}:
                fractions=[]
                for i,values in enumerate(scores):
                    peers=[i]+[j for c,identity,j in values if c>=cutoff][:neighbors]
                    fractions.append(sum(reds[j] for j in peers)/len(peers))
                cache[(*key,cutoff,neighbors)]=fractions
        stress=np.asarray([cache[(p['lookback'],p['minimum_observations'],p['cutoff'],p['neighbors'])] for p in self.profiles],float)
        damage,counts,amber=threshold_batch(held,greens,stress,self.profiles)
        default_index=self.profiles.index(DEFAULT_CORRELATION)
        actual=material['canonical_breadth']
        need(actual['denominator']==n and actual['greens']==sum(greens) and actual['reds']==sum(reds)
             and actual['green_breadth']==(sum(greens)/n if n else 0.)
             and actual['damaged_breadth']==float(damage[default_index]) and actual['ambers']==int(counts[default_index]),'CORRELATION_DEFAULT_FULL_FRACTIONS')
        for i,label in enumerate(actual['labels']):
            need(label['green']==greens[i] and label['red']==reds[i] and label['amber']==bool(amber[default_index,i])
                 and label['sector_stress']==float(stress[default_index,i]),'CORRELATION_DEFAULT_EVERY_LABEL')
        return damage,actual['green_breadth']
