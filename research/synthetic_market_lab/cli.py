from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapter import export_backtester_tables
from .config import load_config
from .generator import generate_world
from .validate import validate_world


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synthetic-market-lab")
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="generate a deterministic synthetic world")
    generate.add_argument("--config", required=True)
    generate.add_argument("--output", required=True)

    validate = sub.add_parser("validate", help="validate an existing generated world")
    validate.add_argument("--world", required=True)

    adapter = sub.add_parser("export-adapter", help="export public synthetic data to backtester contract tables")
    adapter.add_argument("--world", required=True)
    adapter.add_argument("--output", required=True)
    adapter.add_argument("--benchmark-alias", default=None)

    reproduce = sub.add_parser("reproduce", help="generate, validate, and export adapter tables")
    reproduce.add_argument("--config", required=True)
    reproduce.add_argument("--output", required=True)
    reproduce.add_argument("--adapter-output", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "generate":
        result = generate_world(load_config(args.config), args.output)
    elif args.command == "validate":
        result = validate_world(args.world)
    elif args.command == "export-adapter":
        world = Path(args.world)
        cfg = load_config_from_manifest(world)
        result = export_backtester_tables(world / "public", args.output, benchmark_alias=args.benchmark_alias or cfg["benchmark_adapter_alias"])
    elif args.command == "reproduce":
        cfg = load_config(args.config)
        world = Path(args.output)
        manifest = generate_world(cfg, world)
        validation = validate_world(world)
        adapter_out = Path(args.adapter_output) if args.adapter_output else world / "adapter"
        adapter = export_backtester_tables(world / "public", adapter_out, benchmark_alias=cfg.benchmark_adapter_alias)
        result = {"passed": validation["passed"], "manifest": manifest, "validation": validation, "adapter": adapter}
    else:  # pragma: no cover
        raise AssertionError(args.command)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if not isinstance(result, dict) or result.get("passed", True) else 2


def load_config_from_manifest(world: Path) -> dict:
    return json.loads((world / "manifest.json").read_text(encoding="utf-8"))["config"]


if __name__ == "__main__":
    raise SystemExit(main())
