"""Input-derived historical lifecycle continuity for independent launches."""
from pathlib import Path
import os
import unittest
from backtester import research_champion_spy_iwm_observers as observer
from backtester import research_champion_spy_iwm_fresh_launch as fresh


class LifecycleTests(unittest.TestCase):
    def test_only_prior_effective_events_apply(self):
        events={'2014-01-03':{'old':{},'unmapped':{}},'2020-01-02':{'boundary':{}},'2025-01-02':{'future':{}}}
        ids={'old':7,'boundary':8,'future':9}
        self.assertEqual(fresh.prior_retired(events,ids,'2020-01-02'),{7})
        events['2025-01-02']['old']={'future_mutation':True}
        self.assertEqual(fresh.prior_retired(events,ids,'2020-01-02'),{7})

    def test_source_order_does_not_change_retirement(self):
        events={'2019-12-31':{'a':{}},'2018-01-02':{'b':{}}}
        ids={'a':1,'b':2}
        self.assertEqual(fresh.prior_retired(events,ids,'2020-01-02'),
                         fresh.prior_retired(dict(reversed(list(events.items()))),ids,'2020-01-02'))

    def test_malformed_effective_date_refuses(self):
        with self.assertRaises(ValueError):
            fresh.prior_retired({'not-a-date':{'a':{}}},{'a':1},'2020-01-02')

    def test_fresh_source_assembles_preserving_frozen_classes(self):
        witness=os.environ.get('OBSERVER_ASSEMBLY_WITNESS')
        if witness:
            source=Path(witness).read_text()
        else:
            from backtester import research_champion_corrected_classification as corrected
            source=corrected.build_source(Path('/tmp/fresh-lifecycle-assembly'))
        assembled=observer.install(source,'fresh5')
        revised=fresh.install_lifecycle(assembled)
        self.assertEqual(observer.class_hashes(revised),observer.class_hashes(source))
        self.assertLess(revised.index('_retired_tids.update(_prior_retired'),
                        revised.index('for y in range(_observers.warmup_start.year'))
        self.assertIn('_observers.launch(book)',revised)
        with self.assertRaises(RuntimeError): fresh.install_lifecycle(revised)


if __name__=='__main__': unittest.main()
