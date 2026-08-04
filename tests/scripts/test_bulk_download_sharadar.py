"""scripts/bulk-download-sharadar.sh — a script that handles a live API key.

The dangerous failures here are not "fails to download". They are:

  * leaking the key (into `ps`, shell history, a log line, an image layer)
  * EXECUTING .env instead of reading it — `source` runs the file, so a stray
    backtick in any value, including one that arrived by a git pull, becomes a
    shell command in a script people run without reading
  * leaving a truncated ZIP that the skip-check mistakes for a finished one, so
    a partial download is never retried

So those are what is asserted. The download itself is not testable without the
network and a paid key, and pretending otherwise with a mock would test the mock.
"""
import os
import re
import subprocess

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SCRIPT = os.path.join(ROOT, "scripts", "bulk-download-sharadar.sh")


@pytest.fixture(scope="module")
def src() -> str:
    with open(SCRIPT) as f:
        return f.read()


def test_script_exists_and_is_executable():
    assert os.path.isfile(SCRIPT)
    assert os.access(SCRIPT, os.X_OK)


def test_bash_syntax_is_valid():
    r = subprocess.run(["bash", "-n", SCRIPT], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ── the key ─────────────────────────────────────────────────────────────────

def test_env_is_PARSED_never_sourced(src):
    """`source .env` executes it. A download script must not be a code path for
    whatever ends up in an environment file."""
    assert not re.search(r"^\s*(source|\.)\s+.*\.env", src, re.M)
    assert "SHARADAR_API_KEY[[:space:]]*=" in src, "must parse the assignment"


def test_the_key_never_reaches_the_command_line(src):
    """Anything on argv is visible in `ps` to every user on the box and lands in
    shell history. The key may cross only through the environment."""
    assert "-e NDL_KEY=" in src
    assert not re.search(r"--api[-_]?key[= ]\$", src)
    assert not re.search(r'echo .*\$KEY(?!\{?#)', src), "the key must never be echoed"


def test_only_the_key_LENGTH_is_reported(src):
    """Confirming a key loaded is genuinely useful — a silently empty variable is
    the failure people waste an hour on. The length says that without saying the
    secret."""
    assert "${#KEY}" in src


def test_an_empty_key_is_a_hard_failure(src):
    """Falling through to the download with an empty key produces a 403 several
    minutes in, which reads as a network problem rather than a missing secret."""
    assert re.search(r'if \[ -z "\$KEY" \]', src)


def test_the_key_is_not_written_into_an_image_or_a_file(src):
    assert "docker build" not in src
    assert not re.search(r'\$KEY"?\s*>', src), "the key must never be redirected to a file"


# ── behaviour that costs hours when wrong ───────────────────────────────────

def test_partial_downloads_cannot_masquerade_as_complete(src):
    """THE one that bites. The skip-check treats an existing ZIP as done, so an
    interrupted export must not leave a file at the final name — otherwise the
    truncated download is skipped forever and the corpus is quietly short."""
    assert ".part" in src
    assert "os.replace(part, final)" in src
    assert "os.remove(part)" in src, "a failed export must clean up its partial"


def test_existing_tables_are_skipped_by_default(src):
    """SEP alone is several GB. Re-fetching it to pick up TICKERS after a partial
    batch would be absurd."""
    assert "--force" in src and 'FORCE" -eq 0' in src


def test_it_never_writes_to_the_database(src):
    """This is a FASTER ROUTE to the same data, not a second source. Loading is a
    separate step and a separate decision — a download script that also mutates
    the corpus makes 'I just grabbed the files' a lie."""
    # Checks for OPERATIONS, not for the word "bt-postgres". The first version
    # banned the token and failed twice on the script's own explanation and on
    # the closing message that TELLS the operator nothing was loaded — a test
    # that could only pass by deleting the sentence stating the guarantee.
    # Comments are stripped; what remains must contain no way to reach a DB.
    code = "\n".join(re.sub(r"#.*$", "", ln) for ln in src.splitlines())
    for forbidden in ("psql", "BT_DATABASE_URL", "INSERT INTO", "COPY ",
                      "compose exec", "asyncpg", "psycopg"):
        assert forbidden not in code, f"{forbidden!r} — this script must not load data"


def test_the_env_var_name_matches_what_bt_data_actually_reads():
    """A script that reads a DIFFERENT variable than the service would send
    someone hunting for a key that was there all along."""
    client = open(os.path.join(ROOT, "services", "bt-data", "app",
                               "sharadar_client.py")).read()
    assert 'os.getenv("SHARADAR_API_KEY"' in client
    assert "SHARADAR_API_KEY" in open(SCRIPT).read()


# ── the parser, exercised rather than grepped ───────────────────────────────

@pytest.mark.parametrize("line,expected", [
    ("SHARADAR_API_KEY=plainkey", "plainkey"),
    ('SHARADAR_API_KEY="quoted-key"', "quoted-key"),
    ("SHARADAR_API_KEY='single'", "single"),
    ("  SHARADAR_API_KEY = spaced ", "spaced"),
    ("SHARADAR_API_KEY=with-crlf\r", "with-crlf"),
])
def test_key_parser_handles_real_env_shapes(tmp_path, src, line, expected):
    """Env files come from humans, Windows editors and copy-paste. Each of these
    reads as a valid assignment to every other tool that touches .env."""
    (tmp_path / ".env").write_text(f"OTHER=1\n{line}\nMORE=2\n")
    extract = re.search(r'KEY="\$\(sed(.*?)\)"', src, re.S).group(0)
    extract = extract.replace('"$ROOT/.env"', '".env"')
    r = subprocess.run(["bash", "-c", f'{extract}\nprintf "%s" "$KEY"'],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected


def test_a_commented_out_key_is_not_picked_up(tmp_path, src):
    """`#SHARADAR_API_KEY=old` must not resurrect a retired key — the operator
    commented it out on purpose."""
    (tmp_path / ".env").write_text("#SHARADAR_API_KEY=commented\n")
    extract = re.search(r'KEY="\$\(sed(.*?)\)"', src, re.S).group(0)
    extract = extract.replace('"$ROOT/.env"', '".env"')
    r = subprocess.run(["bash", "-c", f'{extract}\nprintf "%s" "$KEY"'],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.stdout == ""
