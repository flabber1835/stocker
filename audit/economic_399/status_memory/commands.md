# Local validation command record

Working directory: `C:/GitHub/stocker/.codex-tmp/status-memory-worktree`.
Python executable:
`C:/Users/mbron/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
The commands below use `python` for that same interpreter. PowerShell redirected
each process's complete output to the correspondingly named `status-memory-*.log`
in `C:/GitHub/stocker/.codex-tmp/`; ZIP members retain those bytes.

```powershell
python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_status_memory.py tests/sentinel/test_production_state.py tests/sentinel/test_canonical_session_kernel.py tests/sentinel/test_issue_252_253_session_envelope.py
# status-memory-fixed-lifecycle.log: 77 passed, 59.61 s

python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_shadow_observation.py tests/sentinel/test_rolling_runtime.py tests/sentinel/test_rolling_daily.py tests/sentinel/test_rolling_recovery.py tests/sentinel/test_rolling_initialization.py tests/sentinel/test_panel_concurrency.py tests/sentinel/test_panel.py
# status-memory-release-regression.log: 277 passed, 700.65 s

$bootstrap = @'
import os,shutil,subprocess,sys
shutil.copytree('/source','/tmp/repo',ignore=shutil.ignore_patterns('.git','.env','__pycache__'))
os.chdir('/tmp/repo')
os.environ.update(PYTHONPATH='/tmp/repo:/tmp/repo/shared:/tmp/repo/scripts',SENTINEL_REPO_ROOT='/tmp/repo',PYTHONDONTWRITEBYTECODE='1')
raise SystemExit(subprocess.run([sys.executable,'-u','audit/economic_399/status_memory/mutations.py',*sys.argv[1:]]).returncode)
'@
docker run --rm --network none --memory 4g --cpus 2 --mount type=bind,source=C:/GitHub/stocker/.codex-tmp/status-memory-worktree,target=/source,readonly --entrypoint python sentinel-test:ci -u -c $bootstrap
docker run --rm --network none --memory 4g --cpus 2 --mount type=bind,source=C:/GitHub/stocker/.codex-tmp/status-memory-worktree,target=/source,readonly --entrypoint python sentinel-test:ci -u -c $bootstrap --case decoder-lifetime
# The second invocation isolates the corrected lifecycle mutant; earlier nine
# controls are unchanged. Logs: release-mutations and lifecycle-mutant.

$evidence='C:/GitHub/stocker/.codex-tmp/status-memory-acceptance-evidence'
python audit/economic_399/status_memory/run_fixture.py --evidence $evidence
# Runs in its own terminal; logs publication, initialization and later advance.

# Separate terminal, after fixture_ready:
python audit/economic_399/status_memory/run_reader.py --evidence $evidence --repeats 2
python audit/economic_399/status_memory/run_reader.py --evidence $evidence --surface http
python audit/economic_399/status_memory/run_reader.py --evidence $evidence --mutant-retain-seed
# Negative control expects exit 137 AND Docker OOMKilled=true; ordinary failure
# alone is not a passing resource falsifier.
Set-Content -LiteralPath "$evidence/advance" -Value advance
# Wait for advanced_fixture_ready before the next two commands:
python audit/economic_399/status_memory/run_reader.py --evidence $evidence --repeats 2
python audit/economic_399/status_memory/run_reader.py --evidence $evidence --surface http
docker exec sentinel-status-memory-fixture python /source/audit/economic_399/status_memory/economic_oracle.py
Set-Content -LiteralPath "$evidence/stop" -Value stop

$env:PYTHONPATH='C:/GitHub/stocker/.codex-tmp/lint-deps'
python -m pyflakes sentinel/core/session.py sentinel/shadow_observation.py sentinel/rolling_checkpoint.py sentinel/rolling_daily_checkpoint.py sentinel/rolling_runtime.py tests/sentinel/test_status_memory.py audit/economic_399/status_memory/probe.py audit/economic_399/status_memory/run_reader.py audit/economic_399/status_memory/run_fixture.py audit/economic_399/status_memory/mutations.py
python tools/validate_test_responsibility.py --base origin/main --output C:/GitHub/stocker/.codex-tmp/status-memory-final-ownership.json
git diff --check origin/main
```

The full Docker arguments and generated reader code are printed at the start of
every scale-reader log. Final acceptance does not use `--diagnostic-bound-context`.
The original single-request baseline and earlier input-phase evidence are retained
unchanged in their original directories and commits.
