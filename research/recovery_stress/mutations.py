"""Fault injection in isolated imports, preserving all experiment sources."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

FAULTS = {
    "leader_relative_comparator_restored": ("model", '"recent_r20 >= wc_r20", "recent_r20 > 0"', '"recent_r20 >= wc_r20", "recent_r20 >= wc_r20"'),
    "market_relative_comparator_restored": ("model", '"spy20 >= wc_r20", "spy20 > 0"', '"spy20 >= wc_r20", "spy20 >= wc_r20"'),
    "gap_moved_to_close": ("market", "raw_open=bar.raw_open*factor", "raw_open=bar.raw_open"),
    "future_price_level_not_adjusted": ("market", "market.prices[bar.security_id] *= factor", "market.prices[bar.security_id] *= 1."),
    "policy_identity_not_changed": ("model", "base.identity = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()", "base.identity = base.identity"),
}


def main():
    results = {}
    with tempfile.TemporaryDirectory(prefix="recovery-stress-mutants-") as temp:
        for name,(module,before,after) in FAULTS.items():
            raw = Path(f"research/recovery_stress/{module}.py").read_text()
            assert raw.count(before) == 1
            path = Path(temp)/f"{name}.py"
            path.write_text(raw.replace(before,after))
            env = dict(os.environ)
            env[f"RECOVERY_STRESS_MUTANT_{module.upper()}"] = str(path)
            result = subprocess.run([sys.executable,"-m","pytest","research/recovery_stress/test_recovery.py","-q",
                "-p","no:cacheprovider","--basetemp",str(Path(temp)/f"test-{name}")],env=env,capture_output=True,text=True)
            killed = result.returncode == 1 and " failed" in result.stdout and "ERROR " not in result.stdout
            results[name] = dict(killed=killed,exit_code=result.returncode,summary=result.stdout.strip().splitlines()[-1])
            if not killed:
                raise AssertionError(result.stdout+result.stderr)
    Path("audit/recovery-relapse-screen/mutations.json").write_text(json.dumps(results,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps(results))


if __name__ == "__main__":
    main()
