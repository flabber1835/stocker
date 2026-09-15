"""Accounting and PIT-label falsifiers using hand-calculated portfolios."""
import copy
import gzip
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from composition import Observer, composition, instrument
from publication import finalize, payloads


class Slot(SimpleNamespace):
    def held(self):
        return self.qty > 0 and self.tid >= 0


def fixture():
    def metadata(tid, date):
        return dict(security_id="ID1", ticker="OLD" if date < "2020-02-03" else "NEW",
                    effective_session="2010-01-01" if date < "2020-02-03" else "2020-02-03",
                    security_type="common", security_type_source="strict-prior-test")
    return dict(ds="2020-02-03", book=SimpleNamespace(
        cash=300., receivables=[(1, 100.)], slots=[Slot(tid=0, qty=6.)], last_raw={0: 95.}),
        eq=1000., eff={"A": .55}, a_d=0., sid=["ID1"], clraw=[100.], _metadata=metadata)


class CompositionTests(unittest.TestCase):
    def test_hand_calculated_weights_and_distinct_target_timing(self):
        rows, session = composition(fixture())
        by = {r["bucket"]: r for r in rows}
        self.assertEqual(by["STOCK"]["shadow_weight_pct"], 60.)
        self.assertEqual(by["STOCK"]["effective_model_weight_pct"], 33.)
        self.assertEqual(by["CORE_CASH"]["effective_model_weight_pct"], 16.5)
        self.assertAlmostEqual(by["DIVIDEND_RECEIVABLE"]["effective_model_weight_pct"], 5.5)
        self.assertAlmostEqual(by["TBILL_SLEEVE"]["effective_model_weight_pct"], 45.)
        self.assertEqual(by["STOCK"]["next_target_model_weight_pct"], 0.)
        self.assertEqual(by["TBILL_SLEEVE"]["next_target_model_weight_pct"], 100.)
        self.assertAlmostEqual(session["effective_weight_sum_pct"], 100.)

    def test_historical_ticker_rename(self):
        state = fixture()
        state["ds"] = "2020-01-31"
        first = composition(state)[0][0]
        state["ds"] = "2020-02-03"
        second = composition(state)[0][0]
        self.assertEqual((first["ticker"], second["ticker"]), ("OLD", "NEW"))
        self.assertEqual(first["security_id"], second["security_id"])

    def test_split_neutrality_and_no_observer_mutation(self):
        state = fixture()
        before = copy.deepcopy(state)
        old = composition(state)
        self.assertEqual(state, before)
        state["book"].slots[0].qty *= 2
        state["clraw"][0] /= 2
        new = composition(state)
        self.assertEqual(old[0][0]["reference_value"], new[0][0]["reference_value"])
        self.assertEqual(old[0][0]["effective_model_weight_pct"], new[0][0]["effective_model_weight_pct"])

    def test_two_lots_aggregate_under_permanent_identity(self):
        state = fixture()
        state["book"].slots = [Slot(tid=0, qty=2.), Slot(tid=0, qty=4.)]
        rows, summary = composition(state)
        self.assertEqual(rows[0]["quantity"], 6.)
        self.assertEqual((summary["stock_count"], summary["stock_lot_count"]), (1, 2))

    def test_carried_mark_is_disclosed(self):
        state = fixture()
        state["clraw"][0] = float("nan")
        state["eq"] = 970.
        rows, summary = composition(state)
        self.assertEqual(rows[0]["mark"], 95.)
        self.assertEqual(summary["carried_mark_count"], 1)

    def test_zero_exposure_is_all_defensive_sleeve(self):
        state = fixture()
        state["eff"]["A"] = 0.
        rows, _ = composition(state)
        self.assertEqual(rows[-1]["effective_model_weight_pct"], 100.)
        self.assertTrue(all(r["effective_model_weight_pct"] == 0 for r in rows[:-1]))

    def test_cash_only_portfolio(self):
        state = fixture()
        state["book"].slots = []
        state["book"].cash = 900.
        rows, summary = composition(state)
        self.assertEqual(summary["stock_count"], 0)
        self.assertAlmostEqual(sum(r["effective_model_weight_pct"] for r in rows), 100.)

    def test_invalid_evidence_is_rejected(self):
        for change in (
            lambda s: s.update(eq=1001.),
            lambda s: s.update(_metadata=lambda tid, date: None),
            lambda s: s.update(_metadata=lambda tid, date: dict(ticker="FUTURE", effective_session="2099-01-01")),
            lambda s: s.update(_metadata=lambda tid, date: dict(ticker="X", effective_session="2000-01-01", security_id="WRONG")),
            lambda s: s["book"].last_raw.clear() or s.update(clraw=[float("nan")]),
            lambda s: s["book"].receivables.append((1, -1.)),
            lambda s: s.update(a_d=1.2),
        ):
            with self.subTest(change=change):
                state = fixture()
                change(state)
                with self.assertRaises((ValueError, TypeError)):
                    composition(state)

    def test_observer_stream_and_duplicate_session_rejection(self):
        state = fixture()
        for key in ("dd", "r5", "r10", "r20", "r40", "ddam5", "spy20", "volacc", "recent_r20", "recent_r40"):
            state[key] = 0.
        state.update(stops20=0, open_eq=1000., dam_b=.1, green_b=.8, native_target=0.,
                     effective_native=0., a_reason="SEVERE")
        with tempfile.TemporaryDirectory() as temp:
            observer = Observer(Path(temp))
            try:
                observer(state)
                with self.assertRaises(ValueError):
                    observer(state)
            finally:
                observer.close()
            text = (Path(temp) / "observations.csv").read_text()
            self.assertIn("current_effective_native_preclose", text)
            self.assertEqual(len(text.splitlines()), 2)

    def test_partial_evidence_and_lossless_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = "date,ticker,weight\n2020-01-31,OLD,33.0\n".encode()
            (root / "portfolio-composition.csv").write_bytes(raw)
            (root / "FAILURE.json").write_text(json.dumps(dict(error="deliberate failure", error_type="ValueError")))
            finalize(root)
            self.assertIn("INCOMPLETE_OR_FAILED", (root / "SUMMARY.md").read_text())
            data = payloads(root)
            self.assertEqual(gzip.decompress(data["portfolio-composition.csv.gz"]), raw)
            self.assertIn("deliberate failure", data["SUMMARY.md"].decode())

    def test_independent_export_validation_rejects_weight_redistribution(self):
        import pandas as pd
        from run import verify_export_rows
        rows, summary = composition(fixture())
        frame, sessions = pd.DataFrame(rows), pd.DataFrame([summary])
        verify_export_rows(frame, sessions)
        # Conservation still holds, but the stock/cash split has been corrupted.
        frame.loc[0, "effective_model_weight_pct"] += 1
        frame.loc[1, "effective_model_weight_pct"] -= 1
        with self.assertRaises(ValueError):
            verify_export_rows(frame, sessions)

    def test_frozen_source_instrumentation_and_mutant_rejection(self):
        path = Path(os.environ["CHAMPION_SOURCE"])
        source = path.read_text()
        result = instrument(source)
        self.assertEqual(result.replace("\n            _cert_observe(locals())", ""), source)
        with self.assertRaises(ValueError):
            instrument(source.replace("ENTRY_W = 0.05", "ENTRY_W = 0.06"))


if __name__ == "__main__":
    unittest.main()
