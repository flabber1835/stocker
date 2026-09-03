import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
MODULE_PATH = TOOLS / "pit_russell_preserved_full_membership_validate_v2.py"
SPEC = importlib.util.spec_from_file_location("pit_russell_preserved_full_membership_validate_v2", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class PreservedRussellV2Tests(unittest.TestCase):
    def test_short_all_caps_company_names_are_not_rejected(self):
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
        <doc><page width="612" height="792"><flow><block>
          <line><word xMin="75" yMin="50">Company</word><word xMin="257" yMin="50">Symbol</word></line>
          <line><word xMin="327" yMin="50">Company</word><word xMin="509" yMin="50">Symbol</word></line>
          <line><word xMin="75" yMin="100">INTUIT</word></line>
          <line><word xMin="257" yMin="100">INTU</word></line>
          <line><word xMin="327" yMin="100">KEYCORP</word></line>
          <line><word xMin="509" yMin="100">KEY</word></line>
        </block></flow></page></doc>'''
        rows = mod.parse_preserved_bbox(xml)
        self.assertEqual(
            [("INTU", "INTUIT"), ("KEY", "KEYCORP")],
            [(r.ticker, r.company) for r in rows],
        )

    def test_ltd_allowed_only_as_symbol_exception(self):
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
        <doc><page width="612" height="792"><flow><block>
          <line><word xMin="75" yMin="50">Company</word><word xMin="257" yMin="50">Symbol</word></line>
          <line><word xMin="75" yMin="100">LIMITED</word><word xMin="110" yMin="100">BRANDS</word><word xMin="150" yMin="100">INC</word></line>
          <line><word xMin="257" yMin="100">LTD</word></line>
        </block></flow></page></doc>'''
        rows = mod.parse_preserved_bbox(xml)
        self.assertEqual([("LTD", "LIMITED BRANDS INC")], [(r.ticker, r.company) for r in rows])
        self.assertTrue(mod.is_preserved_ticker("LTD"))
        self.assertFalse(mod.is_preserved_ticker("INDEX"))


if __name__ == "__main__":
    unittest.main()
