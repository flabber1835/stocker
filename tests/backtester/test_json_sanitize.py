"""_json_sanitize — NaN/Inf must never reach a Postgres jsonb write.

Production incident: a short sample made distribution std / DSR math NaN;
json.dumps emitted a bare `NaN` token and Postgres rejected the insert with
`invalid input syntax for type json`, failing the whole (otherwise successful)
config-replay — which the evaluator then reported as "backtester unavailable"."""
import json
import math

import numpy as np

from app.main import _json_sanitize


def test_nan_and_inf_become_null_recursively():
    dirty = {
        "sharpe": float("nan"),
        "dd": float("-inf"),
        "nested": {"std": np.float64("nan"), "ok": 1.5},
        "rows": [{"r": float("inf")}, {"r": 0.01}, None, "x"],
    }
    clean = _json_sanitize(dirty)
    assert clean["sharpe"] is None and clean["dd"] is None
    assert clean["nested"]["std"] is None and clean["nested"]["ok"] == 1.5
    assert clean["rows"][0]["r"] is None and clean["rows"][1]["r"] == 0.01
    # The proof that matters: the result is valid STRICT json (Postgres-acceptable).
    json.dumps(clean, allow_nan=False)


def test_finite_values_and_types_untouched():
    obj = {"a": 1, "b": "s", "c": [1.25, True, None], "d": {"e": 0.0}}
    assert _json_sanitize(obj) == obj


def test_numpy_floats_covered():
    assert _json_sanitize(np.float64("inf")) is None
    assert _json_sanitize(np.float64(2.5)) == 2.5
