#!/usr/bin/env python3
"""Fail-closed Docker/Compose execution envelope for Sentinel production paths."""
from __future__ import annotations

import argparse
import os
import sys
from typing import Mapping, Optional, Sequence


CANONICAL_PROJECT = "sentinel"
CANONICAL_CONTEXT = "default"
CANONICAL_COMPOSE_ENV = {
    "COMPOSE_DISABLE_ENV_FILE": "1",
    "COMPOSE_ENV_FILES": "/dev/null",
}
DOCKER_SELECTOR_KEYS = frozenset({
    "DOCKER_HOST",
    "DOCKER_CONFIG",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
    "DOCKER_TLS",
    "DOCKER_API_VERSION",
    "DOCKER_DEFAULT_PLATFORM",
    "BUILDKIT_HOST",
    "BUILDX_BUILDER",
})
SAFE_AUTOMATION_GLOBAL_VALUE_OPTIONS = frozenset({
    "--ansi", "--parallel", "--progress",
})
GRAPH_GLOBAL_OPTIONS = frozenset({
    "--env-file", "-f", "--file", "-p", "--project-name",
    "--project-directory",
})
READ_ONLY_COMMANDS = frozenset({
    "config", "ps", "logs", "top", "events", "port", "images", "ls",
    "version", "help", "stats", "volumes", "wait",
})
RISK_REDUCING_COMMANDS = frozenset({"stop", "pause", "kill"})
RUN_SAFE_FLAGS = frozenset({"--rm", "-T", "--no-deps", "--quiet", "-q", "--interactive", "-i"})
RUN_FORBIDDEN_VALUE_OPTIONS = frozenset({
    "--cap-add", "--cap-drop", "--entrypoint", "--env", "-e",
    "--env-from-file", "--label", "-l", "--name", "--publish", "-p",
    "--pull", "--user", "-u", "--volume", "-v", "--workdir", "-w",
})
EXEC_SAFE_FLAGS = frozenset({"-T"})
EXEC_FORBIDDEN_VALUE_OPTIONS = frozenset({
    "--env", "-e", "--env-file", "--user", "-u", "--workdir", "-w",
})
DOWN_FORBIDDEN = frozenset({"-v", "--volumes", "--remove-orphans", "--rmi"})
RM_FORBIDDEN = frozenset({"-v", "--volumes"})
UP_FORBIDDEN = frozenset({
    "--build", "--pull", "--remove-orphans", "--renew-anon-volumes", "-V", "--scale",
})


class ExecutionEnvelopeRefused(ValueError):
    pass


def _refuse(message: str) -> None:
    raise ExecutionEnvelopeRefused(message)


def validate_environment(env: Mapping[str, str]) -> None:
    """Reject ambient selectors that can move the validated Docker/Compose authority."""
    context = str(env.get("DOCKER_CONTEXT", "") or "").strip()
    if context and context != CANONICAL_CONTEXT:
        _refuse("Docker context must be the local default context")
    for key in DOCKER_SELECTOR_KEYS:
        if str(env.get(key, "") or "").strip():
            _refuse("ambient Docker selector is not allowed: %s" % key)
    for key, value in env.items():
        if not key.startswith("COMPOSE_"):
            continue
        observed = str(value or "").strip()
        if key in CANONICAL_COMPOSE_ENV:
            if observed and observed != CANONICAL_COMPOSE_ENV[key]:
                _refuse("Compose environment differs from the canonical Sentinel envelope: %s" % key)
            continue
        if observed:
            _refuse("ambient Compose control is not allowed: %s" % key)


def _option_name(token: str) -> str:
    return token.split("=", 1)[0]


def _reject_attached_graph_global(token: str) -> bool:
    return ((token.startswith("-f") and token != "-f")
            or (token.startswith("-p") and token != "-p")
            or any(token.startswith(name + "=") for name in (
                "--env-file", "--file", "--project-name", "--project-directory")))


def _consume_globals(surface: str, arguments: Sequence[str]) -> int:
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if not token.startswith("-") or token == "-":
            return index
        if token == "--":
            _refuse("Compose command boundary may not be supplied explicitly")
        name = _option_name(token)
        if name in GRAPH_GLOBAL_OPTIONS or _reject_attached_graph_global(token):
            _refuse("Compose graph/project/env overrides are not allowed: %s" % name)
        if name == "--profile":
            if surface != "automation":
                _refuse("profiles are fixed by the Sentinel wrapper")
            if "=" in token:
                value = token.split("=", 1)[1]
            else:
                if index + 1 >= len(arguments):
                    _refuse("Compose profile requires a value")
                index += 1
                value = arguments[index]
            if value != "automation":
                _refuse("automation wrapper accepts only the fixed automation profile")
            index += 1
            continue
        if surface == "automation" and name in SAFE_AUTOMATION_GLOBAL_VALUE_OPTIONS:
            if "=" not in token:
                if index + 1 >= len(arguments):
                    _refuse("Compose option %s requires a value" % name)
                index += 1
            index += 1
            continue
        _refuse("Compose global option is outside the Sentinel execution envelope: %s" % token)
    return index


def _contains_option(arguments: Sequence[str], forbidden) -> Optional[str]:
    for token in arguments:
        name = _option_name(token)
        if token in forbidden or name in forbidden:
            return name
    return None


def _validate_run(arguments: Sequence[str]) -> None:
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token == "--":
            _refuse("Compose run requires an explicit service before application arguments")
        if not token.startswith("-") or token == "-":
            return
        name = _option_name(token)
        if token in RUN_SAFE_FLAGS:
            index += 1
            continue
        if name in RUN_FORBIDDEN_VALUE_OPTIONS:
            _refuse("Compose run execution override is not allowed: %s" % name)
        _refuse("Compose run option is outside the Sentinel execution envelope: %s" % token)
    _refuse("Compose run invocation has no service")


def _validate_exec(arguments: Sequence[str]) -> None:
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token == "--":
            _refuse("Compose exec requires an explicit service before application arguments")
        if not token.startswith("-") or token == "-":
            return
        name = _option_name(token)
        if token in EXEC_SAFE_FLAGS:
            index += 1
            continue
        if name in EXEC_FORBIDDEN_VALUE_OPTIONS or token == "--privileged":
            _refuse("Compose exec execution override is not allowed: %s" % name)
        _refuse("Compose exec option is outside the Sentinel execution envelope: %s" % token)
    _refuse("Compose exec invocation has no service")


def validate_compose_arguments(surface: str, arguments: Sequence[str]) -> None:
    if surface not in {"base", "automation"}:
        _refuse("unknown Sentinel Compose surface")
    args = list(arguments)
    if not args:
        return
    command_index = _consume_globals(surface, args)
    if command_index >= len(args):
        return
    command = args[command_index]
    tail = args[command_index + 1:]
    if command in READ_ONLY_COMMANDS or command in RISK_REDUCING_COMMANDS:
        return
    if command == "down":
        bad = _contains_option(tail, DOWN_FORBIDDEN)
        if bad:
            _refuse("destructive Compose down option is not allowed: %s" % bad)
        return
    if command == "rm":
        bad = _contains_option(tail, RM_FORBIDDEN)
        if bad:
            _refuse("destructive Compose rm option is not allowed: %s" % bad)
        return
    if command in {"up", "create"}:
        bad = _contains_option(tail, UP_FORBIDDEN)
        if bad:
            _refuse("Compose startup option can change reviewed runtime/state identity: %s" % bad)
        return
    if command in {"start", "restart", "unpause"}:
        return
    if command == "run":
        _validate_run(tail)
        return
    if command == "exec":
        _validate_exec(tail)
        return
    _refuse("Compose command is outside the Sentinel execution envelope: %s" % command)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("environment")
    compose = sub.add_parser("compose")
    compose.add_argument("--surface", choices=("base", "automation"), required=True)
    compose.add_argument("arguments", nargs=argparse.REMAINDER)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        validate_environment(os.environ)
        if args.action == "compose":
            values = list(args.arguments)
            if values[:1] == ["--"]:
                values = values[1:]
            validate_compose_arguments(args.surface, values)
        return 0
    except ExecutionEnvelopeRefused as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
