"""Exact ACTIONS economic values survive the durable compatibility schema."""
from sentinel.feed import actions


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, _sql, _params):
        return None

    def fetchall(self):
        return list(self.rows)


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _Cursor(self.rows)


def test_active_actions_preserves_float_contract_and_exact_source_spelling():
    exact = "6342.596697"
    rounded_compatibility_value = 6342.596697
    conn = _Conn([(
        "row-id",
        {"date": "2026-01-02", "action": "dividend", "ticker": "AAA",
         "name": None, "value": exact, "contraticker": None,
         "contraname": None},
        "AAA", "2026-01-02", "dividend", None,
        rounded_compatibility_value, None, None,
    )])

    rows = actions.active_rows(
        conn, start="2026-01-02", end="2026-01-02")

    value = rows[0]["value"]
    assert isinstance(value, float)
    assert value == rounded_compatibility_value
    assert str(value) == exact


def test_active_actions_legacy_payload_falls_back_to_compatibility_value():
    conn = _Conn([(
        "legacy-row",
        {"date": "2026-01-02", "action": "dividend", "ticker": "AAA",
         "name": None, "value": None, "contraticker": None,
         "contraname": None},
        "AAA", "2026-01-02", "dividend", None,
        0.47, None, None,
    )])

    rows = actions.active_rows(
        conn, start="2026-01-02", end="2026-01-02")

    assert rows[0]["value"] == 0.47