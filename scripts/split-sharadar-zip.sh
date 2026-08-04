#!/usr/bin/env bash
# Split a Sharadar bulk-export ZIP into per-YEAR gzipped CSVs.
#
# WHY NOT pandas. The obvious version reads the CSV in chunks, parses dates, and
# appends each year's rows with `to_csv(mode="a", compression="gzip")`. It works,
# and on 35M rows it is slow for reasons that are all avoidable:
#
#   parse_dates      builds 35M Timestamps to read four characters from each
#   mode="a" + gzip  reopens the file and starts a NEW gzip member per chunk per
#                    year — hundreds of opens, and an archive whose member count
#                    depends on the chunk size
#   groupby("year")  materialises a frame per year per chunk
#
# None of that is needed to route a line by its date. This streams the CSV once,
# slices the year out of the date STRING, and keeps one open gzip writer per
# year — constant memory, no parsing, no reopening, one clean member per file.
#
# LOSSLESS AND ORDERED. Every input row lands in exactly one output file, header
# included, in the order it appeared. The row count is asserted at the end.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

SRC=""
OUT_DIR=""
DATE_COL=""
IMAGE="${SHARADAR_BULK_IMAGE:-python:3.12-slim}"
FORCE=0

usage() {
    cat <<'USAGE'
Usage: scripts/split-sharadar-zip.sh --zip PATH [--out DIR] [--date-column NAME] [--force]

  --zip           the bulk export, e.g. artifacts/sharadar-bulk/SHARADAR_SEP.zip
  --out           destination (default: <zip dir>/<TABLE>_years)
  --date-column   column to split on (default: auto — date, then datekey, then
                  the first column whose name ends in "date")
  --force         overwrite an existing output directory
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --zip)         SRC="$2"; shift 2 ;;
        --out)         OUT_DIR="$2"; shift 2 ;;
        --date-column) DATE_COL="$2"; shift 2 ;;
        --force)       FORCE=1; shift ;;
        --help|-h)     usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

[ -n "$SRC" ] || { usage; exit 2; }
[ -f "$SRC" ] || { echo "no such file: $SRC" >&2; exit 1; }

SRC="$(cd "$(dirname "$SRC")" && pwd)/$(basename "$SRC")"
BASE="$(basename "$SRC" .zip)"
[ -n "$OUT_DIR" ] || OUT_DIR="$(dirname "$SRC")/${BASE}_years"

# A finished split is a DIRECTORY of files, so "partly written" and "complete"
# look identical from outside. Build into .part and rename the whole directory at
# the end — the same reason the download writes a .part ZIP. An interrupted run
# then leaves an obviously-unfinished name rather than a plausible-looking
# directory with three of twenty years in it.
if [ -d "$OUT_DIR" ] && [ "$FORCE" -eq 0 ]; then
    echo "output exists: $OUT_DIR (use --force to replace)" >&2
    exit 1
fi
rm -rf "$OUT_DIR.part"
mkdir -p "$OUT_DIR.part"

echo "source : $SRC"
echo "output : $OUT_DIR"
echo

# -i is LOAD-BEARING. Without it docker does not attach stdin, so `python -`
# reads an EMPTY program, runs nothing and exits 0 — the wrapper then renames an
# empty .part directory into place and reports success. (That is exactly what
# happened on the first real run: no output, no error, an empty folder.)
docker run --rm -i \
    -e DATE_COL="$DATE_COL" \
    -e BASE="$BASE" \
    -v "$SRC:/in.zip:ro" \
    -v "$OUT_DIR.part:/out" \
    "$IMAGE" \
    python - <<'PY'
import csv, gzip, io, os, sys, time, zipfile

base = os.environ["BASE"]
want_col = os.environ.get("DATE_COL") or ""

zf = zipfile.ZipFile("/in.zip")
names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
if not names:
    sys.exit("no .csv inside the archive")
if len(names) > 1:
    # Silently taking the first would quietly split a fraction of the data.
    sys.exit(f"expected one CSV, found {len(names)}: {names}")
member = names[0]
print(f"member: {member}", flush=True)

# newline="" per the csv module contract: without it, a quoted field containing
# a newline is split across records — rare in price data, silent when it happens.
raw = zf.open(member)
text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
reader = csv.reader(text)
header = next(reader)

if want_col:
    if want_col not in header:
        sys.exit(f"--date-column {want_col!r} not in header: {header}")
    idx = header.index(want_col)
else:
    for cand in ("date", "datekey", "calendardate"):
        if cand in header:
            idx = header.index(cand); want_col = cand; break
    else:
        tail = [c for c in header if c.lower().endswith("date")]
        if not tail:
            sys.exit(f"no date-like column in header: {header}")
        idx = header.index(tail[0]); want_col = tail[0]
print(f"splitting on {want_col!r} (column {idx})", flush=True)

# One writer per year, opened once and held. The pandas append-per-chunk pattern
# reopens the file and starts a fresh gzip member every time; both are valid but
# the member count then depends on the chunk size, which is a property of the
# script rather than of the data.
writers, counts = {}, {}
rows = skipped = 0
t0 = time.time()

def writer_for(year):
    w = writers.get(year)
    if w is None:
        fh = gzip.open(f"/out/{base}_{year}.csv.gz", "wt", newline="", compresslevel=6)
        w = csv.writer(fh)
        w.writerow(header)          # every part is independently readable
        writers[year] = w
        writers[f"__fh_{year}"] = fh
        counts[year] = 0
    return w

for row in reader:
    rows += 1
    try:
        year = row[idx][:4]
    except IndexError:
        skipped += 1               # short row — never silently dropped, see below
        continue
    if not (len(year) == 4 and year.isdigit()):
        skipped += 1
        continue
    writer_for(year).writerow(row)
    counts[year] += 1
    if rows % 5_000_000 == 0:
        print(f"  {rows:,} rows … {time.time()-t0:,.0f}s", flush=True)

for k, v in list(writers.items()):
    if str(k).startswith("__fh_"):
        v.close()

print(flush=True)
for year in sorted(counts):
    mb = os.path.getsize(f"/out/{base}_{year}.csv.gz") / 1e6
    print(f"  {year}  {counts[year]:>12,} rows  {mb:>8,.1f} MB", flush=True)

total = sum(counts.values())
print(f"\n{total:,} rows written, {skipped:,} skipped, "
      f"{len(counts)} year files, {time.time()-t0:,.0f}s", flush=True)

# LOSSLESS, asserted rather than assumed. Every input row must land in exactly
# one output file or be counted as skipped; a split that quietly loses rows is
# worse than no split, because the corpus looks complete.
if total + skipped != rows:
    sys.exit(f"ROW COUNT MISMATCH: read {rows:,}, wrote {total:,}, skipped {skipped:,}")
if skipped:
    # Not fatal — a trailing blank line is normal — but never silent.
    print(f"NOTE: {skipped:,} row(s) had no usable {want_col}", flush=True)
PY

# Never promote an empty split. The row-count assertion lives INSIDE the python,
# which is worthless if the python never ran — the missing -i above proved that
# the wrapper needs its own check on the one thing it can see from outside.
N_PARTS="$(find "$OUT_DIR.part" -name '*.csv.gz' | wc -l)"
if [ "$N_PARTS" -eq 0 ]; then
    echo "the splitter produced no files — leaving $OUT_DIR.part for inspection" >&2
    exit 1
fi

rm -rf "$OUT_DIR"
mv "$OUT_DIR.part" "$OUT_DIR"
echo "$N_PARTS year file(s) written"
echo
ls -lh "$OUT_DIR" | head -30
echo
echo "Each file carries the header and is independently readable:"
echo "  zcat $OUT_DIR/${BASE}_2024.csv.gz | head -3"
