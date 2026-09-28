# Local acquisition resource qualification

This work measures the production acquisition path before changing its resource
policy. It grants no GO, economic, broker or NAS authority. The input profiles
are explicit synthetic loads, not a claim about the current vendor row counts.

## Experiment design

Use separate containers for a streaming synthetic Tables/ZIP server, PostgreSQL
16 and the acquisition worker. Generate fixture CSVs incrementally on disk in
the provider container; never construct the full input in the measured worker.
The worker uses the real Sharadar HTTP/export client, rolling reference and
price acquisition, PostgreSQL staging and ordered staged reader. It does not
build a strategy book or publish a production snapshot. Check exact row counts,
reference cardinalities and ordered-read counts so omitted work cannot look fast.

The worker has the production 4 GiB memory limit, PostgreSQL 1 GiB and 1 GiB shared
memory. Set memory+swap equal to memory, and record the actual Docker settings
and cgroup limits. The fixture server has its own 512 MiB ceiling. Use a private
internal Docker network, fixed synthetic credentials, unique container/volume
names, and no host ports. Do not inspect or change another project's resources.
Run the standard-library Python controller directly on the host. No experiment
container receives the Docker socket. The production 500-second acquisition
callback budget also applies; container capacity alone cannot establish timely
completion.

The signed automation service has a smaller 2 GiB / 1 CPU envelope than the
manual 4 GiB / 2 CPU runtime. Repeat the daily profile at that smaller budget
as a separate acquisition-only result. It does not include supervisor, book
construction or other callback memory, so it is not complete automation capacity
qualification.

Profiles:

- Startup: 5,000 priced securities, 22,000 ticker records, 250,000 distinct
  historical actions and the actual 379-session formation window.
- Daily: the same reference load with the actual 300-session price window.
- Stress: 10,000 priced securities, 30,000 ticker records, 1,000,000 actions and
  379 sessions. This is a larger synthetic envelope, not a vendor maximum.
- Repeat acquisition against the same generation to observe verified cache
  reuse and retained disk size, with the same semantic checks as a cold read.

Measure wall time and process RSS at phase boundaries, process lifetime peak RSS,
container memory peaks/events, cache bytes/counts and partial-file bytes, database
and staging sizes, WAL bytes and PostgreSQL temporary spill. A frequent background
sampler measures anonymous memory and working-set high water while work runs;
kernel cgroup lifetime peaks capture short allocations the sampler might miss.
Report full cgroup memory (including file cache) separately from working set.

A profile passes only when all semantic checks complete, container limits match,
no OOM is recorded, and measured working-set peaks stay below 80% of the worker
and database ceilings. Missing memory evidence cannot produce PASS. Record the
exact source identity and fixture dimensions. A timeout, killed process or
measurement failure is a retained failed result, never an omitted scenario.

Use a deliberately smaller worker limit as a sensitivity experiment. An OOM is
an observed capacity refusal, not proof of graceful application recovery. Keep
that result distinct from successful production-budget profiles.

Cache retention also needs a small isolated falsifier: 64 files is a count limit,
not a byte quota. Measure its behavior across differently sized artifacts and
report the absence of a byte bound. Do not silently introduce a guessed resource
limit or claim that a few successful profiles prove bounded use for every input.

## Reproduction

Use Python 3.12 and Docker with Linux containers and cgroup v2. The controller
uses only Python's standard library; the image supplies acquisition dependencies.
Build the repository's test image first using its normal build procedure, then:

```sh
docker build --pull=false -t acquisition-resources:local -f tools/acquisition_resources/Dockerfile .
python -m tools.acquisition_resources.runner --image acquisition-resources:local --profile smoke --output artifacts/acquisition-resources/smoke.json
python -m tools.acquisition_resources.runner --image acquisition-resources:local --profile startup --output artifacts/acquisition-resources/startup.json
python -m tools.acquisition_resources.runner --image acquisition-resources:local --profile daily --output artifacts/acquisition-resources/daily.json
python -m tools.acquisition_resources.runner --image acquisition-resources:local --profile stress --output artifacts/acquisition-resources/stress.json
python -m tools.acquisition_resources.runner --image acquisition-resources:local --profile daily --worker-memory-mib 2048 --worker-cpus 1 --output artifacts/acquisition-resources/automation-budget.json
python -m tools.acquisition_resources.runner --image acquisition-resources:local --profile startup --worker-memory-mib 256 --cycles 1 --output artifacts/acquisition-resources/constrained.json
docker run --rm --network none acquisition-resources:local -m tools.acquisition_resources.cache_probe
```

Run these sequentially. The constrained experiment is expected to return a
nonzero exit; examine its retained verdict and Docker OOM state rather than
classifying every nonzero exit as memory pressure. Each report has adjacent
worker/provider/database logs, including on failure. Cleanup targets only names
generated by that invocation; it never prunes shared images or other projects.
Failed cleanup is recorded and makes the experiment fail.

The source data are compressible synthetic CSVs with explicit dimensions. They
exercise the real parsing and staging path but do not establish the vendor's
worst-case field widths, compression ratio, action count, or response latency.
Fixture generation is outside worker timing and memory. Worker RSS, kernel
cgroup peak (including file cache), and sampled working set are different
measurements. Memory and temporary-cache samples can miss brief allocations;
zero observed partial bytes does not prove that temporary files never existed.
Database `temp_bytes` is cumulative SQL spill, not peak concurrent temporary
disk consumption. Repeating acquisition in one process also measures retained
allocator memory; it does not model an entirely new worker process.

## Measured results (2026-09-27)

The production source is unchanged from verified main
`a3a141e045ed546cb41107bd02f6c448a76fc1bd`; its measured Sentinel Python-source
SHA256 is `7a83946028ba9cdfc23ddf467c2f62e52157a4284ecd34486aa85d83132e2f31`.
The worker image is
`sha256:94c4590523825720fd253693559e8789988961879077a22b5babd8f6020d1b66`.
The local Docker Desktop VM has about 7.4 GiB available. These measurements use
a fresh disposable database and Docker volumes, not the NAS's retained corpus or
USB storage. Timings include local machine contention and cannot predict NAS
throughput.

| Profile | Price rows per cycle | Cold / cached acquisition seconds | Worker working-set peak MiB | Database working-set peak MiB | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| [Startup](../audit/acquisition_resources/startup.json), 4 GiB / 2 CPUs | 1,895,000 | 90.3 / 100.6 | 448.7 | 759.2 | PASS within profile |
| [Daily](../audit/acquisition_resources/daily.json), 4 GiB / 2 CPUs | 1,500,000 | 77.9 / 78.9 | 443.7 | 534.9 | PASS within profile |
| [Daily at automation budget](../audit/acquisition_resources/automation-budget.json), 2 GiB / 1 CPU | 1,500,000 | 66.8 / 70.1 | 443.4 | 611.1 | PASS, acquisition only |
| [Stress](../audit/acquisition_resources/stress.json), 4 GiB / 2 CPUs | 3,790,000 | 202.1 / 182.0 | 1,254.7 | 947.1 | FAIL: database headroom |

The startup input contains 153.49 MiB of exported CSV in 15.88 MiB of ZIPs;
daily contains 126.48 MiB in 12.91 MiB of ZIPs. Startup downloaded 21 ZIPs and
daily 17. Each cached cycle added zero ZIP downloads, matched the cold cycle's
ordered database digest, and retained exactly the same cache size with no
partial files left. The sampler observed temporary cache writes up to 196 KiB
and 96 KiB respectively; these are sampled values, not guaranteed maxima.

After both cycles the startup database occupied 431.66 MiB and had spilled
430.73 MiB cumulatively to temporary SQL files. Daily occupied 250.84 MiB and
had spilled 340.94 MiB. WAL occupied 16 MiB in these unlogged-staging experiments.
These measurements do not include durable candidate/publication writes or WAL
archival and backup amplification.

The stress profile completed both cycles with matching counts and ordered
digests, no extra ZIP downloads on repetition, and no OOM events. It nevertheless
failed the predeclared 20% reserve criterion: database working set reached
947.1 MiB, and its full cgroup peak reached the 1,024 MiB ceiling. Working set
includes active file cache and shared memory; the sampled anonymous-memory peak
was only 89.3 MiB. This is a reserve failure, not a demonstrated database crash
or proof that 947 MiB was unreclaimable. Do not raise limits or weaken the
criterion simply to relabel this run PASS.

Stress inputs comprised 348.96 MiB of exported CSV and 34.23 MiB of ZIPs. The
database occupied 626.44 MiB after the second cycle and accumulated 1,190.88 MiB
of temporary SQL writes. The worker's process RSS peak was 1,300.43 MiB; its
full cgroup peak was 1,301.07 MiB. Its sampled temporary-cache peak was 1.53 MiB.

The [256 MiB sensitivity run](../audit/acquisition_resources/constrained.json)
was killed during reference acquisition: Docker recorded `OOMKilled=true` and
exit 137. The controller retained a failed result and cleaned up its disposable
resources. This proves the experiment observes an actual enforced memory
failure; it does not prove graceful production recovery from an OOM.

Validation:

```sh
python -m pytest tests/sentinel/test_acquisition_resources.py tests/sentinel/test_source_acquisition_lifecycle.py tests/sentinel/test_sharadar_snapshot_export.py tests/sentinel/test_resource_envelope.py -q -p no:cacheprovider
# 51 passed; includes five killed guard-removal mutants.
python tools/validate_test_responsibility.py --base a3a141e045ed546cb41107bd02f6c448a76fc1bd
# PASS after committing the new test: 509 modules, no unowned/incident additions.
```

The actual PR-event `_require_incident_anti_regrowth()` check also passed against
the committed tree. All 18 final resource tests also passed with current production
source and new tools/tests mounted into the CI image's `/app` and `/work` layout.
Python 3.12
compilation and `git diff --check` passed. No full economic suite was needed:
the implementation changes are confined to this local harness and its tests.
All experiment containers, networks and volumes were removed successfully.
The cache probe's measurements are retained in
[cache.json](../audit/acquisition_resources/cache.json).

The resulting qualification is deliberately partial: the tested startup and
daily acquisition loads meet the local criteria, including daily acquisition at
the automation budget. The larger stress load does not meet database headroom,
and arbitrary provider payloads still have no enforced byte envelope. Full
production capacity, automation and NAS qualification remain open.

## Remaining boundaries

The later [resource containment change](acquisition-resource-containment.md)
adds fixed ZIP/CSV/object-count limits and reserves aggregate cache bytes under
a global lock before writes. The unbounded-export/cache findings below describe
the original experiment, not the updated production behavior. Process RSS,
database growth and real-provider/NAS sizing remain separate qualification work.

The code scrub found these limits on the claim:

- `snapshot_export._safe_download` buffers the full compressed file;
  `_csv_rows` materializes its decoded rows. Monthly SEP partitioning limits
  sessions per file, but neither response bytes nor CSV expansion has a ceiling.
- `rolling_source.references` retains the full ACTIONS history and ticker
  metadata. Its deduplication temporarily allocates additional collections.
  A bounded price window does not bound the growing action history.
- `acquisition_work.save_cached` retains 64 ZIPs. The isolated disk probe kept
  that count while increasing retained ZIP bytes from 262,144 to 1,048,576.
  There is no aggregate byte quota, and cleanup follows writing the new file.
- Cache reuse avoids ZIP transfer, but still parses and stages the rows.
  PostgreSQL spills sorts and retains physical space after scratch rows are
  replaced. Two successful cycles establish neither steady-state disk size nor
  long-running vacuum behavior.

These are observed or inspected resource boundaries, not newly enforced
production guards. A future bounded-acquisition change needs an explicit policy
for compressed bytes, decoded data and retained cache size while preserving
complete-source evidence. Passing this experiment must not silently close that
work or issue #235's wider memory concerns.

The NAS's older kernel, physical RAM competition, USB/volume throughput and real
vendor payload distribution still require target measurement. Candidate building,
historical formation, complete GO, backup overlap and sustained daily operation
are separate scopes. Local synthetic acquisition results do not close them.
