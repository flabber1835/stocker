"""scripts/split-sharadar-zip.sh — splitting a bulk export into per-year parts.

The failure that matters is SILENT ROW LOSS. A split that drops rows leaves a
corpus that looks complete: every year file is present, each opens fine, and
nothing downstream can tell that a slice of history is missing. So the script
asserts its own row arithmetic, and these tests run the real splitter against
fixtures rather than grepping it — a lossless-ness claim verified by string
matching is not verified.
"""
import csv
import glob
import gzip
import io
import os
import re
import subprocess
import sys
import zipfile

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SCRIPT = os.path.join(ROOT, "scripts", "split-sharadar-zip.sh")


@pytest.fixture(scope="module")
def src() -> str:
    with open(SCRIPT) as f:
        return f.read()


@pytest.fixture(scope="module")
def splitter(src: str) -> str:
    """The inline python, extracted between its heredoc markers so the tests
    exercise the SAME code the container runs. Re-implementing it here would
    test the copy."""
    lines = src.splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip() == "python - <<'PY'")
    end = next(i for i, l in enumerate(lines) if i > start and l == "PY")
    return "\n".join(lines[start + 1:end])


def _run(splitter, tmp_path, rows, *, member="SHARADAR_SEP.csv", env=None):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    zpath = tmp_path / "in.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, buf.getvalue())
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    code = (splitter
            .replace('"/in.zip"', f'"{zpath}"')
            .replace("/out/", f"{out}/"))
    script = tmp_path / "s.py"
    script.write_text(code)
    e = {**os.environ, "BASE": "T", "DATE_COL": "", **(env or {})}
    return subprocess.run([sys.executable, str(script)], capture_output=True,
                          text=True, env=e), out


def _read_back(out) -> tuple[list, list]:
    header, body = None, []
    for f in sorted(glob.glob(f"{out}/*.csv.gz")):
        with gzip.open(f, "rt", newline="") as fh:
            rows = list(csv.reader(fh))
        assert rows, f"{f} is empty"
        if header is None:
            header = rows[0]
        assert rows[0] == header, f"{f} has a different header"
        body += rows[1:]
    return header, body


def _fixture(years=(2022, 2023, 2024), per_year=50):
    rows = [["ticker", "date", "close"]]
    for y in years:
        for i in range(per_year):
            rows.append([f"T{i % 5}", f"{y}-0{(i % 9) + 1}-15", str(i)])
    return rows


# ── the property that matters ───────────────────────────────────────────────

def test_the_split_is_LOSSLESS(splitter, tmp_path):
    """Concatenating the parts must reproduce the input exactly. A split that
    quietly loses rows is worse than no split: the corpus looks complete."""
    rows = _fixture()
    r, out = _run(splitter, tmp_path, rows)
    assert r.returncode == 0, r.stderr
    _header, body = _read_back(out)
    assert sorted(map(tuple, body)) == sorted(map(tuple, rows[1:]))


def test_every_part_carries_the_header(splitter, tmp_path):
    """Each year file has to be independently readable — a part without a header
    is only usable if you happen to know the column order."""
    r, out = _run(splitter, tmp_path, _fixture())
    assert r.returncode == 0, r.stderr
    header, _ = _read_back(out)
    assert header == ["ticker", "date", "close"]


def test_rows_land_in_the_year_named_on_the_file(splitter, tmp_path):
    """The whole point. A routing bug that still writes every row would pass a
    pure row-count check."""
    r, out = _run(splitter, tmp_path, _fixture())
    assert r.returncode == 0, r.stderr
    for f in sorted(glob.glob(f"{out}/*.csv.gz")):
        year = os.path.basename(f).split("_")[-1].split(".")[0]
        with gzip.open(f, "rt", newline="") as fh:
            for row in list(csv.reader(fh))[1:]:
                assert row[1].startswith(year), f"{row} in {f}"


def test_row_order_is_preserved_within_a_year(splitter, tmp_path):
    """Streaming means the parts stay in source order. Worth pinning: a future
    'optimisation' that buffers and sorts would change what a downstream loader
    sees without changing any count."""
    rows = [["ticker", "date", "close"]] + [
        ["A", "2024-01-15", str(i)] for i in range(200)]
    r, out = _run(splitter, tmp_path, rows)
    assert r.returncode == 0, r.stderr
    _h, body = _read_back(out)
    assert [x[2] for x in body] == [str(i) for i in range(200)]


# ── rows that are not rows ──────────────────────────────────────────────────

def test_an_unusable_date_is_COUNTED_not_silently_dropped(splitter, tmp_path):
    """Skipping is fine; skipping quietly is not. The count is what lets someone
    say 'one blank trailing line' rather than wonder."""
    rows = _fixture() + [["BAD", "", "1"], ["BAD", "notadate", "2"]]
    r, out = _run(splitter, tmp_path, rows)
    assert r.returncode == 0, r.stderr
    assert "2 row(s) had no usable" in r.stdout
    _h, body = _read_back(out)
    assert len(body) == len(rows) - 1 - 2


def test_a_short_row_does_not_crash_the_run(splitter, tmp_path):
    """35M rows from a vendor will contain something malformed. Dying at row
    30M and losing the whole pass is the wrong response."""
    rows = _fixture() + [["ONLYONE"]]
    r, out = _run(splitter, tmp_path, rows)
    assert r.returncode == 0, r.stderr
    assert "1 row(s) had no usable" in r.stdout


# ── refusing rather than guessing ───────────────────────────────────────────

def test_multiple_csvs_are_REFUSED_rather_than_guessed(splitter, tmp_path):
    """Taking the first would split a fraction of the data and report success."""
    zpath = tmp_path / "in.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("a.csv", "ticker,date\nA,2024-01-01\n")
        z.writestr("b.csv", "ticker,date\nB,2024-01-01\n")
    out = tmp_path / "out"; out.mkdir()
    code = (splitter.replace('"/in.zip"', f'"{zpath}"').replace("/out/", f"{out}/"))
    s = tmp_path / "s.py"; s.write_text(code)
    r = subprocess.run([sys.executable, str(s)], capture_output=True, text=True,
                       env={**os.environ, "BASE": "T", "DATE_COL": ""})
    assert r.returncode != 0
    assert "expected one CSV" in (r.stdout + r.stderr)


def test_a_missing_date_column_fails_loudly(splitter, tmp_path):
    rows = [["ticker", "close"], ["A", "1"]]
    r, _out = _run(splitter, tmp_path, rows)
    assert r.returncode != 0
    assert "date-like" in (r.stdout + r.stderr)


def test_an_explicit_date_column_that_does_not_exist_is_refused(splitter, tmp_path):
    r, _out = _run(splitter, tmp_path, _fixture(), env={"DATE_COL": "nope"})
    assert r.returncode != 0
    assert "nope" in (r.stdout + r.stderr)


def test_it_auto_detects_datekey_for_SF1_shaped_exports(splitter, tmp_path):
    """SEP uses `date`, SF1 uses `datekey`. One script, both tables."""
    rows = [["ticker", "datekey", "revenue"],
            ["A", "2023-02-03", "1"], ["B", "2024-02-03", "2"]]
    r, out = _run(splitter, tmp_path, rows)
    assert r.returncode == 0, r.stderr
    assert "'datekey'" in r.stdout
    assert len(glob.glob(f"{out}/*.csv.gz")) == 2


# ── the script around it ────────────────────────────────────────────────────

def test_bash_syntax_is_valid():
    r = subprocess.run(["bash", "-n", SCRIPT], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_output_is_built_in_a_part_directory_and_renamed(src):
    """A finished split is a DIRECTORY, so 'partly written' and 'complete' look
    identical from outside. Same reason the download writes a .part ZIP."""
    assert ".part" in src
    assert 'mv "$OUT_DIR.part" "$OUT_DIR"' in src


def test_it_refuses_to_clobber_an_existing_split_without_force(src):
    assert 'if [ -d "$OUT_DIR" ] && [ "$FORCE" -eq 0 ]' in src


def test_recursive_replacement_requires_a_dedicated_resolved_target(src):
    guard = src[:src.index('rm -rf -- "$OUT_DIR.part"')]
    assert 'pwd -P' in guard
    assert '*_years' in guard
    assert 'output is a broad protected path' in guard
    assert 'output is a symlink' in guard
    assert 'staging output is a symlink' in guard


def test_recursive_removals_use_the_validated_literal_target(src):
    assert 'rm -rf -- "$OUT_DIR.part"' in src
    assert 'rm -rf -- "$OUT_DIR"' in src


def test_the_source_zip_is_mounted_READ_ONLY(src):
    """A multi-GB download nobody wants to repeat. The splitter has no reason to
    be able to write to it."""
    assert '/in.zip:ro' in src


# ── the wrapper, not the splitter ───────────────────────────────────────────
# Every test above extracts the inline python and runs it directly, which is the
# right way to test the splitting LOGIC and the exact reason the first real run
# failed silently: `docker run` without -i does not attach stdin, so `python -`
# read an empty program, ran nothing and exited 0. The wrapper then renamed an
# empty .part directory into place and printed a success message.
#
# So these test the INVOCATION — the part no amount of splitter testing reaches.

def test_docker_run_attaches_stdin_when_it_pipes_a_heredoc(src):
    """THE bug. A heredoc feeds the container's stdin, which docker only wires up
    with -i. Without it the program is empty and the run silently no-ops."""
    assert "docker run --rm -i" in src, (
        "docker run must pass -i when the program arrives on stdin, or `python -` "
        "reads nothing and exits 0")


def test_an_empty_result_is_a_FAILURE_not_a_success(src):
    """The row-count assertion lives inside the python — worthless if the python
    never ran. The wrapper needs its own check on the one thing it can observe
    from outside: whether any files exist."""
    guard = _guard_block(src)
    assert guard, "no empty-output guard found"
    assert "exit 1" in guard


def _guard_block(src: str) -> str:
    """The `if [ "$N_PARTS" -eq 0 ]` block, isolated. Splitting on the bare token
    picks up the closing echo instead — which is how the first version of these
    two tests failed on a script that was already correct."""
    m = re.search(r'if \[ "\$N_PARTS" -eq 0 \].*?\nfi\n', src, re.S)
    return m.group(0) if m else ""


def test_a_failed_split_leaves_the_part_directory_for_inspection(src):
    """Deleting the evidence on failure means the next person re-runs a multi-GB
    job to see the same error."""
    guard = _guard_block(src)
    assert "leaving" in guard and ".part" in guard
    assert src.index(guard) < src.index('mv "$OUT_DIR.part"')


def test_the_promotion_happens_only_after_the_check(src):
    """Ordering matters: renaming first and validating after would leave a bad
    split at the real name."""
    assert src.index("N_PARTS=") < src.index('mv "$OUT_DIR.part" "$OUT_DIR"')
