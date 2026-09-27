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

## Remaining boundaries

The NAS's older kernel, physical RAM competition, USB/volume throughput and real
vendor payload distribution still require target measurement. Candidate building,
historical formation, complete GO, backup overlap and sustained daily operation
are separate scopes. Local synthetic acquisition results do not close them.
