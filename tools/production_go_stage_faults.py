"""Raising mutations for major stages reached by the canonical GO E2E audit."""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PREPARATION_PHASE = "PHASE C - CERTIFIED FINANCIAL PREPARATION"
FINANCIAL_PHASE = "CERTIFICATION + FINANCIAL READINESS"
POST_PHASE = "POST-VALIDATION HANDOFF"

STAGES = (
    ("schema-feed-authorization", PREPARATION_PHASE),
    ("schema-migration", PREPARATION_PHASE),
    ("feed-catchup", PREPARATION_PHASE),
    ("publication-check", PREPARATION_PHASE),
    ("operational-parity", "PHASE D1 - WEALTH CORE PARITY"),
    ("sharadar-readiness", "PHASE D2 - SHARADAR READINESS"),
    ("database-health", "PHASE D3 - DATABASE FINANCIAL HEALTH"),
    ("validation-evidence", FINANCIAL_PHASE),
    ("requested-target-proof", FINANCIAL_PHASE),
    ("panel-recreation", POST_PHASE),
    ("handoff-write", POST_PHASE),
)

_PREPARATION_HOOKS = {
    "schema-feed-authorization": ("sentinel.backup_guard", "require_writes_permitted"),
    "schema-migration": ("sentinel.schema", "ensure_schema"),
    "feed-catchup": ("sentinel.feed.outage_recovery", "catch_up"),
}
_HOST_HOOKS = {
    "validation-evidence": ("sentinel_go_verified_entry", "go", "write_zip_no_clobber"),
    "requested-target-proof": ("sentinel_go_verified_entry", "", "_write_run_pass"),
    "panel-recreation": ("sentinel_go_post_validate", "", "recreate_panel"),
    "handoff-write": ("sentinel_go_post_validate", "", "atomic_json"),
}


def _failure_code(fault: str, module: str = "", function: str = "") -> str:
    marker = "E2E_STAGE_FAULT:" + fault
    code = ("def __e2e_fail(*args, **kwargs):\n"
            f"    print({marker!r}, flush=True)\n"
            f"    raise RuntimeError({marker!r})\n")
    if module:
        code += ("import importlib as __e2e_importlib\n"
                 f"setattr(__e2e_importlib.import_module({module!r}), "
                 f"{function!r}, __e2e_fail)\n")
    return code


def docker_arguments(argv: list[str], fault: str) -> list[str]:
    """Mutate only the selected production command, preserving every other call."""
    result = list(argv)
    if not result or result[0] != "compose" or "run" not in result:
        return result
    if fault == "operational-parity" and "tools.sentinel_operational_parity" in result:
        index = result.index("-m")
        result[index:index + 2] = ["-c", _failure_code(
            fault, "tools.sentinel_operational_parity", "advance_session")
            + "from tools.sentinel_operational_parity import main\nraise SystemExit(main())"]
        return result
    if "-c" not in result:
        return result
    index = result.index("-c") + 1
    code = result[index]
    if "SENTINEL_GO_PREPARATION=" in code:
        if fault in _PREPARATION_HOOKS:
            result[index] = _failure_code(fault, *_PREPARATION_HOOKS[fault]) + code
        elif fault == "publication-check":
            boundary = "    phase = 'PUBLICATION_CHECK'\n"
            if code.count(boundary) != 1:
                raise RuntimeError("production publication-check boundary changed")
            result[index] = _failure_code(fault) + code.replace(
                boundary, boundary + "    __e2e_fail()\n", 1)
    elif fault == "sharadar-readiness" and "SENTINEL_GO_READINESS=" in code:
        result[index] = _failure_code(
            fault, "sentinel.feed.readiness", "check_readiness") + code
    elif fault == "database-health" and "SENTINEL_GO_DATABASE_HEALTH=" in code:
        result[index] = _failure_code(
            fault, "sentinel.schema", "require_runtime_schema") + code
    return result


def python_main(argv: list[str], fault: str) -> None:
    hook = _HOST_HOOKS.get(fault)
    if hook and argv and argv[0] == "scripts/" + hook[0] + ".py":
        sys.path.insert(0, str(ROOT / "scripts"))
        entry = importlib.import_module(hook[0])
        owner = getattr(entry, hook[1]) if hook[1] else entry
        namespace = {}
        exec(_failure_code(fault), namespace)
        setattr(owner, hook[2], namespace["__e2e_fail"])
        sys.argv = list(argv)
        raise SystemExit(entry.main())
    os.execv(os.environ["E2E_REAL_PYTHON"], [os.environ["E2E_REAL_PYTHON"], *argv])


def main(kind: str) -> None:
    fault = os.environ.get("E2E_INTERNAL_STAGE", "")
    if kind == "python":
        python_main(sys.argv[1:], fault)
    else:
        executable = os.environ["E2E_REAL_DOCKER"]
        os.execv(executable, [executable, *docker_arguments(sys.argv[1:], fault)])
