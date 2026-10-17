from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone

CREDENTIAL_NAMES = ("ALPACA_API_KEY", "ALPACA_SECRET_KEY", "OPENFIGI_API_KEY")
CONFIG_NAMES = (*CREDENTIAL_NAMES, "ALPACA_BASE_URL", "SENTINEL_BACKUP_DIR",
                "SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
MARKER = "SENTINEL_READONLY_SOURCE_DIAGNOSTIC="
PROBE_CODE = r'''
import hashlib, json, os
from datetime import datetime, timezone
marker = "SENTINEL_READONLY_SOURCE_DIAGNOSTIC="
try:
    if os.environ.get("SENTINEL_IMAGE_SOURCE_REVISION") != os.environ["SENTINEL_GIT_COMMIT"]:
        raise RuntimeError("RuntimeRevisionMismatch")
    from sentinel.feed import calendar, openfigi
    from sentinel.feed.alpaca_source import _bounds
    from sentinel.feed.alpaca_transport import Client, BAR_URL, ACTION_URL
    from sentinel.feed.rolling_contract import digest
    from sentinel.shadow_runtime import publication_not_before
    now = datetime.now(timezone.utc)
    day = calendar.latest_closed_session(now)
    while now < publication_not_before(day):
        day = calendar.previous_sessions(day, 2)[0]
    client = Client()
    assets, asset_proof = client.get(client.assets_url,
        {"status":"active", "asset_class":"us_equity"})
    inventory = openfigi.inventory(assets)
    sample = [row for row in inventory if row["ticker"] in ("AAPL", "MSFT")]
    if len(sample) != 2:
        raise RuntimeError("ClassificationSampleUnavailable")
    mapped, mapping_proof = openfigi.Client().mapping(sample)
    if any(openfigi.classify(asset, response)[0] is None
           for asset, response in zip(sample, mapped, strict=True)):
        raise RuntimeError("ClassificationSampleRefused")
    start, end = _bounds(day, day)
    counts, proofs = {}, [asset_proof, mapping_proof]
    for adjustment in ("raw", "split", "all"):
        bars = {}
        for page, proof in client.pages(BAR_URL, {"symbols":"BIL,SPY", "timeframe":"1Day",
                "start":start, "end":end, "limit":10000, "feed":"sip",
                "adjustment":adjustment, "asof":day, "sort":"asc"}, key="bars"):
            proofs.append(proof)
            for symbol, rows in page.items():
                bars.setdefault(symbol, []).extend(rows)
        if set(bars) != {"BIL", "SPY"} or any(len(rows) != 1 for rows in bars.values()):
            raise RuntimeError("BenchmarkCoverageRefused")
        counts[adjustment] = sum(map(len, bars.values()))
    action_count = 0
    for page, proof in client.pages(ACTION_URL,
            {"start":day, "end":day, "limit":1000, "data_quality":"all", "sort":"asc"},
            key="corporate_actions"):
        proofs.append(proof)
        action_count += sum(map(len, page.values()))
    value = {"status":"PASS", "session":day, "inventory_count":len(inventory),
             "classified_count":len(sample), "bar_counts":counts, "action_count":action_count,
             "observation_sha256":digest(proofs), "trading_environment":client.trading_endpoint.environment.value}
except BaseException as exc:
    value = {"status":"FAIL", "error_type":type(exc).__name__}
print(marker + json.dumps(value, sort_keys=True), flush=True)
'''.strip()


def selected_config(path: Path | None, environment: dict[str, str]) -> dict[str, str]:
    selected = {}
    if path is not None:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, separator, raw = line.partition("=")
            key = key.strip()
            if separator and key in CONFIG_NAMES:
                value = raw.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in (chr(34), chr(39)):
                    value = value[1:-1]
                selected[key] = value
    selected.update({key: environment[key] for key in CONFIG_NAMES if key in environment})
    return selected


def backup_availability(config: dict[str, str]) -> dict:
    value = config.get("SENTINEL_BACKUP_DIR", "")
    target = Path(value) if value else None
    present = bool(target and target.is_dir())
    return {"status":"NOT_PROVEN", "configured":target is not None,
            "configured_target_present":present,
            "owner_attestation_configured":config.get("SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED") == "1",
            "reason":"INDEPENDENT_MEDIA_VERIFICATION_REQUIRED" if present
                     else "CONFIGURED_INDEPENDENT_BACKUP_TARGET_UNAVAILABLE"}


def probe_command(image: str, name: str | None = None) -> list[str]:
    if name is not None and re.fullmatch(r"sentinel-source-diagnostic-[a-f0-9]{32}", name) is None:
        raise ValueError("invalid private diagnostic container name")
    return ["docker", "run", "--rm", "-i", *(["--name", name] if name else []), "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--memory", "1g", "--cpus", "1",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "SENTINEL_GIT_COMMIT", "--env", "ALPACA_BASE_URL",
            *[item for name in CREDENTIAL_NAMES for item in ("--env", name)],
            "--entrypoint", "python", image, "-"]


def run_probe(image: str, commit: str, config: dict[str, str], *, runner=subprocess.run) -> dict:
    child_env = {key: value for key, value in os.environ.items() if key not in CONFIG_NAMES}
    child_env.update({name: config[name] for name in CREDENTIAL_NAMES if name in config})
    child_env.update(SENTINEL_GIT_COMMIT=commit,
                     ALPACA_BASE_URL=config.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"))
    started = time.monotonic()
    container_name = "sentinel-source-diagnostic-" + uuid.uuid4().hex
    try:
        completed = runner(probe_command(image, container_name), input=PROBE_CODE, text=True,
                           capture_output=True, timeout=600, check=False, env=child_env)
    finally:
        runner(["docker", "rm", "--force", container_name], text=True, capture_output=True,
               timeout=30, check=False, env={key:value for key,value in child_env.items()
                                           if key not in CREDENTIAL_NAMES})
    raw = (completed.stdout or "") + (completed.stderr or "")
    evidence = {"status":"FAIL", "reason":"PROVIDER_PROBE_OUTPUT_REFUSED",
                "output_sha256":hashlib.sha256(raw.encode()).hexdigest(),
                "elapsed_milliseconds":round((time.monotonic()-started)*1000)}
    lines = [line[len(MARKER):] for line in (completed.stdout or "").splitlines() if line.startswith(MARKER)]
    if completed.returncode == 0 and len(lines) == 1:
        try:
            payload = json.loads(lines[0])
        except ValueError:
            payload = None
        fail = (isinstance(payload, dict) and set(payload) == {"status", "error_type"}
                and payload.get("status") == "FAIL"
                and isinstance(payload.get("error_type"), str)
                and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,79}", payload["error_type"]) is not None)
        passed = (isinstance(payload, dict) and set(payload) == {
                    "status", "session", "inventory_count", "classified_count", "bar_counts",
                    "action_count", "observation_sha256", "trading_environment"}
                  and payload.get("status") == "PASS"
                  and isinstance(payload.get("session"), str)
                  and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", payload["session"]) is not None
                  and all(type(payload.get(key)) is int and payload[key] >= 0
                          for key in ("inventory_count", "classified_count", "action_count"))
                  and payload.get("bar_counts") == {"raw":2, "split":2, "all":2}
                  and isinstance(payload.get("observation_sha256"), str)
                  and re.fullmatch(r"[a-f0-9]{64}", payload["observation_sha256"]) is not None
                  and payload.get("trading_environment") in ("ALPACA_PAPER", "ALPACA_LIVE"))
        if fail or passed:
            evidence.update(payload)
            evidence.pop("reason", None)
    return evidence


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-image", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args(argv)
    if not IMAGE.fullmatch(args.runtime_image) or not COMMIT.fullmatch(args.commit):
        parser.error("an immutable local runtime sha256 and exact 40-character commit are required")
    if (args.output_dir / "report.json").exists():
        parser.error("report already exists; choose a fresh diagnostic directory")
    config = selected_config(args.credentials_file, dict(os.environ))
    report = {"schema":"sentinel.readonly-provider-diagnostic/1", "status":"NOT_PROVEN",
              "runtime_image":args.runtime_image, "git_commit":args.commit,
              "observed_at":datetime.now(timezone.utc).isoformat(),
              "broker_mutation_attempts":0, "financial_publication_attempted":False,
              "backup":backup_availability(config),
              "pending_producer_chain":[
                  "scripts/sentinel-base-backup.sh", "scripts/sentinel-restore-drill.sh",
                  "scripts/sentinel_go_24x7_entry.py::_deployment_preparation_probe",
                  "scripts/sentinel_go_backup_retry.py::RenewalRunner",
                  "scripts/sentinel_go_validate.py::probe_active_wealth_parity",
                  "scripts/sentinel_go_validate.py::probe_sharadar_readiness",
                  "scripts/sentinel_go_validate.py::probe_database_financial_health"],
              "unexecuted":["genuine_base_backup_and_full_restore", "financial_preparation",
                            "formation_restart_parity", "backup_renewal", "financial_readiness",
                            "software_certification", "live_trading_authority"]}
    if args.plan_only:
        report["source"] = {"status":"NOT_PROVEN", "reason":"PLAN_ONLY"}
    elif not all(config.get(name) for name in CREDENTIAL_NAMES[:2]):
        report["source"] = {"status":"NOT_PROVEN", "reason":"DATA_CREDENTIALS_ABSENT"}
    else:
        try:
            report["source"] = run_probe(args.runtime_image, args.commit, config)
        except (OSError, subprocess.SubprocessError) as exc:
            report["source"] = {"status":"FAIL", "error_type":type(exc).__name__}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2)+"\n")
    print(json.dumps(report, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
