"""Original host release evidence and refusal of the retired GO entry point."""
import gzip
from pathlib import Path
import re
import subprocess
import sys

from tools import sentinel_local_go_host_patch as patch


def test_historical_release_sources_match_their_git_witnesses():
    fixtures = Path(__file__).with_name('fixtures')
    new_go = gzip.decompress((fixtures/'go-host-c0d4ed7b.py.gz').read_bytes())
    new_entry = gzip.decompress((fixtures/'go-entry-host-c0d4ed7b.py.gz').read_bytes())
    assert patch.sha(new_go) == '4d6bc501a035b450d6d3d1b750ab2785fc5a4ca8489acb150e11fab0efc4120b'
    assert patch.sha(new_entry) == 'f2ed521a8c97f5e0e3abb9a5163664fee151fd1da33203b8cc3bb547c1216e5c'
    old_go, count = re.subn(rb'^ *"--env", "SENTINEL_TEST_IMAGE_DIGEST",\n', b'', new_go, flags=re.M)
    assert count == 3
    old_entry = new_entry.replace(b'    "SENTINEL_TEST_IMAGE_DIGEST",\n', b'')
    # These independently exported Git dda0195c hashes pin the complete old
    # modules; an inverse transformation alone is not historical evidence.
    assert patch.sha(old_go) == '66cd2d8493e7e722bb5fad95003a3e969e9e56a7ed88b863d2b4bc07f60cca79'
    assert patch.sha(old_entry) == 'f1155a3e73d2cd8abf15150f939f171c3cbbd6c382a27b950980cc7e50f57c8e'


def test_retired_host_patch_refuses_invocation(tmp_path):
    receipt = tmp_path / "receipt.json"
    result = subprocess.run([sys.executable, patch.__file__, str(receipt)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "retired" in result.stderr
    assert not receipt.exists()
