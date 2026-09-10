#!/usr/bin/env bash
# Private, literal ingestion and Docker/Compose authority bridge.

sentinel_require_execution_environment() {
  "$PYTHON" - <<'PY'
import os, sys
canonical = {
    "COMPOSE_DISABLE_ENV_FILE": "1",
    "COMPOSE_ENV_FILES": "/dev/null",
}
docker_keys = (
    "DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY",
    "DOCKER_TLS", "DOCKER_API_VERSION", "DOCKER_DEFAULT_PLATFORM",
    "BUILDKIT_HOST", "BUILDX_BUILDER",
)
context = str(os.environ.get("DOCKER_CONTEXT", "") or "").strip()
if context and context != "default":
    print("REFUSED: Docker context must be the local default context", file=sys.stderr)
    raise SystemExit(2)
for key in docker_keys:
    if str(os.environ.get(key, "") or "").strip():
        print("REFUSED: ambient Docker selector is not allowed: " + key, file=sys.stderr)
        raise SystemExit(2)
for key, value in os.environ.items():
    if not key.startswith("COMPOSE_"):
        continue
    observed = str(value or "").strip()
    if key in canonical:
        if observed and observed != canonical[key]:
            print("REFUSED: Compose environment differs from the canonical Sentinel envelope: " + key,
                  file=sys.stderr)
            raise SystemExit(2)
    elif observed:
        print("REFUSED: ambient Compose control is not allowed: " + key, file=sys.stderr)
        raise SystemExit(2)
raise SystemExit(0)
PY
}

sentinel_require_compose_envelope() {
  local surface="$1"
  shift
  "$PYTHON" - "$surface" "$@" <<'PY'
import sys

surface = sys.argv[1]
args = list(sys.argv[2:])
if surface not in {"base", "automation"}:
    print("REFUSED: unknown Sentinel Compose surface", file=sys.stderr)
    raise SystemExit(2)

value_globals = {
    "--ansi", "--env-file", "-f", "--file", "--parallel", "--profile",
    "--progress", "--project-directory", "-p", "--project-name",
}
switch_globals = {
    "--all-resources", "--compatibility", "--dry-run", "--help", "-h", "--version",
}
graph_globals = {
    "--env-file", "-f", "--file", "--project-directory", "-p", "--project-name",
}
read_only = {
    "config", "ps", "logs", "top", "events", "port", "images", "ls",
    "version", "help", "stats", "volumes",
}
base_start_services = {"sentinel-postgres", "sentinel-panel"}
automation_start_services = {
    "sentinel-postgres", "sentinel-panel", "sentinel-automation",
    "sentinel-alert-dispatcher",
}

def refuse(message):
    print("REFUSED: " + message, file=sys.stderr)
    raise SystemExit(2)

def option_name(token):
    return token.split("=", 1)[0]

def parse_command_options(tokens, *, flags, values):
    positional = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--":
            refuse("explicit option boundary is outside the Compose operational envelope")
        if not token.startswith("-") or token == "-":
            positional.append(token)
            i += 1
            continue
        name = option_name(token)
        if name in flags:
            if "=" in token:
                refuse("boolean Compose option may not carry a value: " + name)
            i += 1
            continue
        if name in values:
            if "=" in token:
                value = token.split("=", 1)[1]
                if not value:
                    refuse("Compose option requires a value: " + name)
            else:
                if i + 1 >= len(tokens):
                    refuse("Compose option requires a value: " + name)
                i += 1
                value = tokens[i]
                if not value:
                    refuse("Compose option requires a value: " + name)
            i += 1
            continue
        refuse("Compose option is outside the Sentinel operational envelope: " + token)
    return positional

def require_start_services(services):
    allowed = base_start_services if surface == "base" else automation_start_services
    unknown = [service for service in services if service not in allowed]
    if unknown:
        refuse("Compose startup service is outside the Sentinel execution envelope: " + unknown[0])
    if (surface == "automation" and "sentinel-automation" in services
            and "sentinel-alert-dispatcher" not in services):
        refuse("automation startup must include sentinel-alert-dispatcher")

controls = []
i = 0
while i < len(args):
    token = args[i]
    if token == "--":
        i += 1
        break
    if not token.startswith("-") or token == "-":
        break
    name = option_name(token)
    attached_short = ((token.startswith("-f") and token != "-f")
                      or (token.startswith("-p") and token != "-p"))
    if attached_short:
        name = token[:2]
        controls.append((name, token[2:]))
        i += 1
        continue
    if name in value_globals:
        if "=" in token:
            value = token.split("=", 1)[1]
        else:
            if i + 1 >= len(args):
                refuse("Compose global option requires a value: " + name)
            i += 1
            value = args[i]
        controls.append((name, value))
        i += 1
        continue
    if name in switch_globals or any(token.startswith(x + "=") for x in switch_globals):
        controls.append((name, None))
        i += 1
        continue
    controls.append((name, None))
    i += 1

if i >= len(args):
    raise SystemExit(0)
command = args[i]
tail = args[i + 1:]

# Inspection is non-authoritative. It may explicitly inspect another graph or
# project, but it cannot start, stop, recreate or remove any resource.
if command in read_only:
    raise SystemExit(0)

for name, value in controls:
    if name in graph_globals:
        refuse("Compose graph/project/env overrides are not allowed for operational commands: " + name)
    if name == "--profile":
        if surface != "automation" or value != "automation":
            refuse("operational profiles are fixed by the Sentinel wrapper")
    elif name in {"--ansi", "--parallel", "--progress"}:
        pass
    else:
        refuse("Compose global option is outside the Sentinel operational envelope: " + name)

if command == "stop":
    parse_command_options(tail, flags=set(), values={"-t", "--timeout"})
    raise SystemExit(0)

if command == "kill":
    # Compose permits custom signals, some of which do not terminate a process.
    # The supported risk-reducing surface therefore permits only default SIGKILL.
    parse_command_options(tail, flags=set(), values=set())
    raise SystemExit(0)

if command == "down":
    parse_command_options(tail, flags=set(), values={"-t", "--timeout"})
    raise SystemExit(0)

if command == "rm":
    parse_command_options(
        tail, flags={"-f", "--force", "-s", "--stop"}, values=set())
    raise SystemExit(0)

if command == "wait":
    # --down-project mutates the project, so wait is only a blocking observation.
    parse_command_options(tail, flags=set(), values=set())
    raise SystemExit(0)

if command in {"up", "create"}:
    if command == "up":
        safe_flags = {
            "-d", "--detach", "--force-recreate", "--no-build", "--no-deps",
            "--no-color", "--no-log-prefix", "--quiet-build", "--quiet-pull",
            "--timestamps", "--wait", "-y", "--yes",
        }
        safe_values = {"-t", "--timeout", "--wait-timeout"}
    else:
        safe_flags = {
            "--force-recreate", "--no-build", "--quiet-pull", "-y", "--yes",
        }
        safe_values = set()
    services = parse_command_options(tail, flags=safe_flags, values=safe_values)
    require_start_services(services)
    raise SystemExit(0)

if command in {"start", "restart", "unpause", "pause"}:
    refuse("stale-container state transitions are not allowed; use the reviewed Compose up/stop path")

if command == "run":
    safe_flags = {"--rm", "-T", "--no-deps", "--quiet", "-q", "--interactive", "-i"}
    forbidden_values = {
        "--cap-add", "--cap-drop", "--entrypoint", "--env", "-e",
        "--env-from-file", "--label", "-l", "--name", "--publish", "-p",
        "--pull", "--user", "-u", "--volume", "-v", "--workdir", "-w",
    }
    j = 0
    while j < len(tail):
        token = tail[j]
        if token == "--":
            refuse("Compose run requires a service before application arguments")
        if not token.startswith("-") or token == "-":
            service = token
            expected = "sentinel" if surface == "base" else "sentinel-automation"
            if service != expected:
                refuse("Compose run service is outside the Sentinel execution envelope: " + service)
            raise SystemExit(0)
        name = option_name(token)
        if token in safe_flags:
            j += 1
            continue
        if name in forbidden_values:
            refuse("Compose run execution override is not allowed: " + name)
        refuse("Compose run option is outside the Sentinel execution envelope: " + token)
    refuse("Compose run invocation has no service")

if command == "exec":
    refuse("generic Compose exec is outside the Sentinel execution envelope")

refuse("Compose command is outside the Sentinel operational envelope: " + command)
PY
}

# Call after selecting the host interpreter.
sentinel_load_environment() {
  local record
  local -a records=()
  while IFS= read -r -d '' record; do
    records+=("$record")
  done < <("$PYTHON" scripts/sentinel_env.py --records "$@")
  if [ "${#records[@]}" -eq 0 ] || \
     [ "${records[${#records[@]}-1]}" != SENTINEL_ENV_COMPLETE_V1 ]; then
    echo "REFUSED: environment preflight did not complete" >&2
    return 2
  fi
  unset 'records[${#records[@]}-1]'
  for record in "${records[@]}"; do
    export "$record" || return 2
  done

  # Bind every supported launcher to one local Docker/Compose authority before
  # any Docker operation. Validate the original process controls, then normalize
  # to the canonical local context and disable implicit Compose env loading.
  sentinel_require_execution_environment || return $?
  unset DOCKER_HOST DOCKER_CONFIG DOCKER_CERT_PATH DOCKER_TLS_VERIFY DOCKER_TLS \
    DOCKER_API_VERSION DOCKER_DEFAULT_PLATFORM BUILDKIT_HOST BUILDX_BUILDER
  unset COMPOSE_FILE COMPOSE_PATH_SEPARATOR COMPOSE_PROJECT_NAME COMPOSE_PROFILES
  export DOCKER_CONTEXT=default
  export COMPOSE_DISABLE_ENV_FILE=1
  export COMPOSE_ENV_FILES=/dev/null
}
