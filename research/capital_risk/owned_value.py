"""Compact exact value-function state. No controller or account advancement."""
import ast
from datetime import date
from decimal import Decimal as D,localcontext
from fractions import Fraction as Q
import math
from owned_grid import need


def ceiling_guard(raw):
    tree=ast.parse(raw);step=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='step')
    reads=[n for n in ast.walk(tree) if isinstance(n,ast.Subscript) and isinstance(n.value,ast.Name)
        and n.value.id=='RULE' and isinstance(n.slice,ast.Constant) and n.slice.value=='active_ceiling']
    need(len(reads)==1,'CEILING_SINGLE_READ')
    assignment=next(n for n in step.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ceiling' for t in n.targets))
    after=next(n for n in step.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='after' for t in n.targets))
    need(reads[0] in list(ast.walk(assignment)) and after.lineno<assignment.lineno,'CEILING_AFTER_STATE_ONLY')
    return {'status':'CEILING_DOES_NOT_ENTER_STATE_TRANSITION','reads':1}


def factor_dependency_guard(raw):
    tree=ast.parse(raw);step=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_advance_strategy_economics')
    returns=[n for n in step.body if isinstance(n,ast.Return)];need(len(returns)==1,'FACTOR_SINGLE_RETURN')
    nav_assignment=next(n for n in step.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='strategy_nav' for t in n.targets))
    nav_loads=[n for n in ast.walk(step) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load) and n.id=='prior_nav']
    pending_loads=[n for n in ast.walk(step) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load) and n.id=='pending']
    need(len(nav_loads)==2 and sum(n in list(ast.walk(nav_assignment)) for n in nav_loads)==1
        and sum(n in list(ast.walk(returns[0])) for n in nav_loads)==1,'NAV_ONLY_MULTIPLICATION_AND_REPORT')
    need(len(pending_loads)==1 and pending_loads[0] in list(ast.walk(returns[0])),'CURRENT_TARGET_REPORT_ONLY')
    need(isinstance(nav_assignment.value,ast.BinOp) and isinstance(nav_assignment.value.op,ast.Mult)
        and isinstance(nav_assignment.value.left,ast.Name) and nav_assignment.value.left.id=='prior_nav'
        and isinstance(nav_assignment.value.right,ast.Name) and nav_assignment.value.right.id=='net_factor','EXACT_SEPARABLE_NAV_OPERATION')
    return {'status':'CANONICAL_FACTOR_NAV_AND_CURRENT_TARGET_INDEPENDENCE','prior_nav_loads':2,'current_pending_loads':1}


def nav_step(nav,factor):
    with localcontext() as ctx:
        ctx.prec=28
        result=D(nav)*D(factor)
        need(result.is_finite() and result>0,'VALUE_POSITIVE_NAV')
        return format(result.normalize(),'f')


class Metric:
    def __init__(self,anchor,saved=None):
        self.value=dict(anchor=anchor[0],initial_nav=anchor[1],peak=anchor[1],worst_nav=anchor[1],worst_peak=anchor[1],
            start=None,end=None,closes=0,nav=anchor[1]) if saved is None else dict(saved)

    def add(self,day,nav):
        s=self.value;n=D(nav);peak=max(D(s['peak']),n)
        # Two products of at most 28 significant digits are exact at precision 80.
        with localcontext() as ctx:
            ctx.prec=80
            worse=n*D(s['worst_peak'])<D(s['worst_nav'])*peak
        if worse:s['worst_nav']=nav;s['worst_peak']=format(peak,'f')
        s['peak']=format(peak,'f');s['nav']=nav;s['end']=day;s['start']=s['start'] or day;s['closes']+=1

    def result(self):
        s=self.value;need(s['closes']>0,'VALUE_METRIC_COMPLETE');initial=Q(s['initial_nav']);nav=Q(s['nav']);multiple=nav/initial
        days=(date.fromisoformat(s['end'])-date.fromisoformat(s['anchor'])).days
        return {'anchor':s['anchor'],'start':s['start'],'end':s['end'],'closes':s['closes'],'initial_nav':str(initial),
            'nav':str(nav),'multiple':str(multiple),'total_return':str(multiple-1),
            'cagr':math.expm1(math.log(float(multiple))*365.2425/days),
            'maximum_drawdown_magnitude':str(1-Q(s['worst_nav'])/Q(s['worst_peak']))}
