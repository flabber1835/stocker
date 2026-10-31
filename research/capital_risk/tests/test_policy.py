from dataclasses import FrozenInstanceError
from datetime import date,timedelta
from fractions import Fraction
import importlib.util
from pathlib import Path
import sys
import unittest

spec=importlib.util.spec_from_file_location("capital_risk_policy",Path(__file__).parents[1]/"policy.py")
p=importlib.util.module_from_spec(spec);sys.modules[spec.name]=p;spec.loader.exec_module(p)


class PolicyTests(unittest.TestCase):
    def test_trim_boundary_target_and_fractional_entitlement(self):
        self.assertIsNone(p.trim_target(quantity=10,nav=10000,raw_close=100))
        self.assertEqual(p.trim_target(quantity='10.01',nav=10000,raw_close=100),8)
        self.assertEqual(p.trim_target(quantity=2,nav=1000,raw_close=100),0)
        self.assertEqual(p.pro_rata_remaining({1:Fraction(3,2),2:Fraction(5,2)},3),
                         {1:Fraction(9,8),2:Fraction(15,8)})
        self.assertEqual(sum(p.pro_rata_remaining({1:Fraction(3,2),2:Fraction(5,2)},3).values()),3)
        for changed in [dict(nav=0),dict(raw_close=0),dict(quantity=-1),dict(upper='.05')]:
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                p.trim_target(**{**dict(quantity=10,nav=10000,raw_close=100),**changed})

    def test_stop_width_exact_causal_window_and_bounds(self):
        days=[(date(2026,1,1)+timedelta(days=i)).isoformat() for i in range(21)]
        values=list(zip(days,[100.0]*21))
        self.assertEqual(p.stop_width(observations=values,expected_sessions=days,current_session=days[-1]),.15)
        wild=list(zip(days,[100.0 if i%2 else 200.0 for i in range(21)]))
        self.assertEqual(p.stop_width(observations=wild,expected_sessions=days,current_session=days[-1]),.30)
        for bad in [values[:-1],values[:-1]+[('2099-01-01',100)],values[:-1]+[(days[-1],0)]]:
            with self.assertRaises(ValueError):
                p.stop_width(observations=bad,expected_sessions=days,current_session=days[-1])

    def test_old_floor_crossing_precedes_update_and_never_loosens(self):
        self.assertEqual(p.ratchet_stop(prior_floor=100,signal_close=100,width=.3,first_owned_close=False),
                         p.StopDecision(True,100.0))
        self.assertEqual(p.ratchet_stop(prior_floor=100,signal_close=101,width=.3,first_owned_close=False).floor,100)
        self.assertEqual(p.ratchet_stop(prior_floor=100,signal_close=200,width=.15,first_owned_close=False).floor,170)
        self.assertEqual(p.ratchet_stop(prior_floor=None,signal_close=100,width=.15,first_owned_close=True),
                         p.StopDecision(False,85.0))
        with self.assertRaises(ValueError):
            p.ratchet_stop(prior_floor=120,signal_close=100,width=.3,first_owned_close=True)
        with self.assertRaises(ValueError):
            p.ratchet_stop(prior_floor=None,signal_close=100,width=.3,first_owned_close=False)

    def advance(self,state,dd,**changed):
        day='2026-01-01' if state.last_session is None else (date.fromisoformat(state.last_session)+timedelta(days=1)).isoformat()
        return p.advance_governor(state,**{**dict(current_session=day,previous_session=state.last_session,
            drawdown=dd,core_r20=.01,damage=.63,green=.20,native_target=1.0),**changed})

    def test_governor_thresholds_and_repeated_second_leg(self):
        initial=p.Governor()
        reduced,target=self.advance(initial,-.155)
        self.assertEqual((reduced.mode,reduced.streak,target),('REDUCED',0,.55))
        out,target=self.advance(reduced,-.25)
        self.assertEqual((out.mode,out.streak,target),('OUT',0,0))
        for i in range(8):
            out,target=self.advance(out,-.199)
            if i<7: self.assertEqual(out.mode,'OUT')
        self.assertEqual((out.mode,out.streak,target),('REDUCED',0,.55))
        for _ in range(8): out,target=self.advance(out,-.124)
        self.assertEqual((out.mode,out.streak,target),('NORMAL',0,1))
        out,target=self.advance(out,-.155)
        self.assertEqual((out.mode,target),('REDUCED',.55))
        # Native rearm flags are deliberately not inputs: the known blind-zone
        # magnitude still escalates a NORMAL governor on a subsequent decline.
        out,target=self.advance(out,-.2737)
        self.assertEqual((out.mode,target),('OUT',0))

    def test_recovery_is_strict_missing_resets_and_native_can_only_reduce(self):
        state,_=self.advance(p.Governor(),-.25)
        for _ in range(8): state,_=self.advance(state,-.20)
        self.assertEqual((state.mode,state.streak),('OUT',8))
        state,_=self.advance(state,-.19,green=None)
        self.assertEqual(state.streak,0)
        state,target=self.advance(state,-.19,native_target=0.0)
        self.assertEqual(target,0.0)
        with self.assertRaises(ValueError): self.advance(state,-.19,damage=float('nan'),green=None)

    def test_governor_restore_identity_cursor_and_state_are_strict(self):
        state,_=self.advance(p.Governor(),-.16)
        self.assertEqual(p.Governor.from_dict(state.to_dict()),state)
        with self.assertRaises(FrozenInstanceError): state.streak=5
        for change in [dict(protocol_sha256='0'*64),dict(extra=True),dict(streak=True),dict(mode='FULL')]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                p.Governor.from_dict({**state.to_dict(),**change})
        with self.assertRaises(ValueError): self.advance(state,-.16,previous_session=None)
        with self.assertRaises(ValueError): self.advance(state,-.16,current_session=state.last_session)


if __name__=='__main__': unittest.main()
