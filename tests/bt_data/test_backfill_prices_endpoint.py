"""The prices-replay endpoint and the script that drives it must agree.

They did not: the endpoint declares `start_date: str` as a bare parameter, which
FastAPI reads from the QUERY STRING, while the script POSTed a JSON body. The
result was HTTP 422 with no indication of the cause, several steps into a deploy.

A contract test rather than an integration test, because the mismatch is visible
in the two source files and needs no running service to catch.
"""
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
MAIN = ROOT / "services" / "bt-data" / "app" / "main.py"
SCRIPT = ROOT / "scripts" / "backfill-sep-raw-close.sh"

SRC = MAIN.read_text()
SH = SCRIPT.read_text()


def endpoint_fn(name: str):
    tree = ast.parse(SRC)
    return next(n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == name)


def test_the_endpoint_takes_query_parameters_not_a_body():
    """A bare `str` annotation is a query param in FastAPI. If this ever becomes
    a Pydantic model the script must change with it, which is what the pairing
    below enforces."""
    fn = endpoint_fn("start_price_backfill")
    args = {a.arg: a for a in fn.args.args}
    assert {"start_date", "end_date"} <= set(args)
    for name in ("start_date", "end_date"):
        ann = args[name].annotation
        assert isinstance(ann, ast.Name) and ann.id == "str", (
            f"{name} is no longer a plain str; if it became a body model, "
            f"scripts/backfill-sep-raw-close.sh must stop sending query params")


def invocation() -> str:
    """The curl that starts the replay, INCLUDING its line continuations.

    A single-line regex missed it entirely — the URL sits on a continuation
    line — and a test that silently matches nothing asserts nothing.
    """
    i = SH.index("jobs/backfill-prices")
    start = SH.rindex("curl", 0, i)
    end = start
    while SH[end:].split("\n", 1)[0].rstrip().endswith("\\"):
        end += len(SH[end:].split("\n", 1)[0]) + 1
    return SH[start:end + len(SH[end:].split("\n", 1)[0])]


def test_the_invocation_is_actually_found():
    """Guards every assertion below: a helper that returns an empty string
    would make all of them vacuously true."""
    assert "jobs/backfill-prices" in invocation()


def test_the_script_sends_them_as_query_parameters():
    call = invocation()
    assert "start_date=" in call and "end_date=" in call, (
        "the script must pass query params; a JSON body gets a bare 422")
    assert "-d " not in call, (
        "a JSON body on this endpoint is rejected as a validation error")


def test_the_script_forces_the_replay():
    """/jobs/backfill skips years already marked complete. Every chunk of the
    corpus is already complete, so without force the replay writes nothing and
    reports success."""
    assert "force=true" in SH


def test_the_script_waits_for_the_job_rather_than_checking_coverage_at_once():
    """The endpoint is fire-and-forget: it returns {"status":"started"} and works
    in a background task. Checking coverage immediately reports ~0% and fails the
    gate on a replay that is running perfectly."""
    started = SH.index("jobs/backfill-prices")
    # Searched AFTER the job is started, not anywhere in the file: the
    # pre-flight mentions bt-engine's /runs/latest in a comment, and matching
    # that made the ordering assertion compare the wrong two positions.
    polled = SH.find("runs/latest", started)
    assert polled != -1, "the script does not poll the run state after starting it"
    assert "backfill_prices" in SH[started:]
    assert polled < SH.index("coverage AFTER"), (
        "coverage must be checked only after the job reaches a terminal state")


def test_a_failed_replay_is_described_as_partial_not_broken():
    """The UPSERT rewrites rows in place, so an interrupted replay leaves a
    partially covered corpus that the gate refuses — nothing is destroyed, and
    re-running resumes."""
    assert "PARTIALLY covered" in SH


def test_the_wait_has_a_ceiling_that_does_not_condemn_the_corpus():
    """Giving up on WAITING is not the same as the data being bad, and a script
    that conflated them would send someone to re-run a finished job."""
    assert "SEP_REPLAY_MAX_MINUTES" in SH
    assert "giving up on WAITING" in SH
