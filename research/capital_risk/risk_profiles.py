"""Frozen finite search space. No financial account operations."""
from typing import Literal
from fractions import Fraction as Q
from pydantic import BaseModel,ConfigDict,Field,model_validator

class Profile(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    id:str=Field(pattern='^[A-Z0-9_]+$')
    family:Literal['ORACLE_H0','ORACLE_P2','LOCAL_RED','BOOK_DAMAGE','CONCENTRATION_BAND']
    entry:int=Field(ge=1,le=5)
    recovery:int=Field(ge=1,le=8)
    retained:str='1'
    threshold:str='0'
    release:str='0'
    rebalance:int=Field(default=0,ge=0,le=21)
    @model_validator(mode='after')
    def limits(self):
        if not 0<=Q(self.retained)<=1 or not 0<=Q(self.threshold)<=1 or not 0<=Q(self.release)<=1:raise ValueError('REFUSED_PROFILE_RANGE')
        if self.family=='CONCENTRATION_BAND' and not 0<Q(self.release)<Q(self.threshold):raise ValueError('REFUSED_PROFILE_BAND')
        return self

def profiles():
    out=[]
    for n in (1,3):
        for label,value in [('0','0'),('55','.55')]:out.append(Profile(id=f'L{n}_KEEP{label}',family='LOCAL_RED',entry=n,recovery=3,retained=value))
    for label,value in [('02','.02'),('04','.04')]:
        for n in (1,3):out.append(Profile(id=f'B{label}_C{n}',family='BOOK_DAMAGE',entry=n,recovery=3,retained='.55',threshold=value))
    for label,ceiling,band in [('10','.10','.08'),('15','.15','.12')]:
        for n in (1,3):out.append(Profile(id=f'C{label}_C{n}',family='CONCENTRATION_BAND',entry=n,recovery=3,threshold=ceiling,release=band,rebalance=21))
    return tuple(out)

def oracle(name):
    if name=='ORACLE_H0':return Profile(id=name,family=name,entry=5,recovery=8,retained='1')
    if name=='ORACLE_P2':return Profile(id=name,family=name,entry=5,recovery=8,retained='.55',threshold='.02')
    raise ValueError('REFUSED_ORACLE_PROFILE')

def selected(name):
    if name.startswith('ORACLE_'):return oracle(name)
    values={p.id:p for p in profiles()}
    if name not in values:raise ValueError('REFUSED_UNDECLARED_SEARCH_PROFILE')
    return values[name]
