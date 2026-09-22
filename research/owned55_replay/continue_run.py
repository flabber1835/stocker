"""Continue finite source-bound owned55 replay segments to the retained end."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def segment_directories(root):
    return sorted(path for path in root.glob("segment-*") if path.is_dir())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "runtime", "archive", "sfp"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    segments = segment_directories(args.root)
    if not segments:
        raise ValueError("require verified pilot checkpoint")
    previous = segments[-1]
    while True:
        status = json.loads((previous/"comparison-status.json").read_text())
        if status["status"] == "COMPLETE":
            print(json.dumps(status), flush=True)
            return
        if status["status"] != "STOPPED_RESUMABLE":
            raise ValueError("previous segment is incomplete or refused")
        number = int(previous.name.split("-")[-1])+1
        following = args.root/f"segment-{number:03d}"
        if following.exists():
            raise ValueError("refuse to overwrite a prior segment")
        command = [sys.executable, "-m", "research.owned55_replay.run",
            "--runtime", str(args.runtime), "--archive", str(args.archive), "--sfp", str(args.sfp),
            "--supplements", str(args.root/"supplements.json"), "--output", str(following),
            "--resume", str(previous/"latest-checkpoint.json"), "--seconds", "3600"]
        print("CONTINUE", status["date"], str(following), flush=True)
        with (args.root/f"segment-{number:03d}.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode:
            raise RuntimeError(f"replay refused ({result.returncode}); inspect {log.name}")
        next_status = json.loads((following/"comparison-status.json").read_text())
        if next_status["date"] <= status["date"]:
            raise ValueError("no forward progress")
        previous = following


if __name__ == "__main__":
    main()
