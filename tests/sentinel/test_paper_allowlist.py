"""Paper-only is an ALLOWLIST, not "everything except one hostname".

The guard used to read:

```python
LIVE_HOSTS = {"api.alpaca.markets"}
if self.endpoint_host in LIVE_HOSTS: refuse
```

which permits everything nobody enumerated:

```text
https://api.alpaca.markets.evil.example/   not in LIVE_HOSTS  -> allowed
http://paper-api.alpaca.markets/           cleartext API key  -> allowed
https://10.0.0.5:8080/                     a proxy to live    -> allowed
https://paper-api.alpaca.markets@evil/     hostname is evil   -> allowed
```

None of those are failures of judgement; they are what a denylist means.

This is not because paper trading is risky. It is that the eventual move from
"paper certified" to anything involving money must require an explicit
architectural change, reviewed as one — never an environment variable.

Two boundaries, because there are two ways in: `SentinelConfig.from_env`, and
`AlpacaExecutionBroker(base_url=...)` which takes a bare string from anyone who
imports it. A wiring commit that built the adapter directly would have bypassed
the appliance's only live-trading protection, and the diff would have looked
like plumbing.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
#: The image splits these: `tests/` is at /work and the package SOURCES are at
#: /work/repo. Reading `sentinel/config.py` through ROOT works on a host and
#: raises FileNotFoundError inside the certified image, where a skip is a
#: failure. `TestNoRepoFileIsReadThroughROOT` caught this on the first run.
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or ROOT)
for p in (str(ROOT), str(ROOT / "shared")):
    if p not in sys.path:
        sys.path.insert(0, p)

from sentinel import config as CFG  # noqa: E402
from sentinel.execution.alpaca import AlpacaExecutionBroker  # noqa: E402

PAPER = "https://paper-api.alpaca.markets"


def a_config(url):
    return CFG.SentinelConfig(alpaca_key="k", alpaca_secret="s", base_url=url,
                              state_dir=Path("/tmp/s"), max_cycles=1,
                              poll_seconds=1.0)


#: Every one of these is the SAME host by DNS and by TLS. Refusing a legitimate
#: operator is its own outage, so normalisation has to be real.
ACCEPTED = [
    PAPER,
    PAPER + "/",
    PAPER + "/v2",
    "https://PAPER-API.Alpaca.Markets",          # case
    "https://paper-api.alpaca.markets.",         # trailing DNS root dot
    "https://paper-api.alpaca.markets:443",      # the default port, written out
]

#: Each with the reason it must be refused, so a future reader can tell an
#: intentional entry from a copy-paste.
REFUSED = [
    ("https://api.alpaca.markets", "the live endpoint"),
    ("https://api.alpaca.markets/", "the live endpoint, trailing slash"),
    ("https://api.alpaca.markets.", "the live endpoint, root dot"),
    ("https://API.Alpaca.Markets", "the live endpoint, mixed case"),
    ("https://api.alpaca.markets.evil.example", "a lookalike SUFFIX domain"),
    ("https://paper-api.alpaca.markets.evil.example", "paper-looking suffix"),
    ("https://evil.example/paper-api.alpaca.markets", "the host is in the PATH"),
    ("https://paper-api.alpaca.markets@evil.example/", "userinfo; host is evil"),
    ("https://user:pw@paper-api.alpaca.markets/", "embedded credentials"),
    ("http://paper-api.alpaca.markets", "cleartext — the key on the wire"),
    ("ws://paper-api.alpaca.markets", "not https"),
    ("https://10.0.0.5:8080", "a bare IP, i.e. any proxy"),
    ("https://127.0.0.1", "loopback"),
    ("https://paper-api.alpaca.markets.", "root dot on a suffix domain")
    if False else ("https://xn--paper-api-alpaca.markets", "punycode lookalike"),
    ("https://paper-api.alpaca.marketsX", "one character longer"),
    ("https://paper-api.alpaca.market", "one character shorter"),
    ("not-a-url", "unparseable"),
    ("", "empty"),
    ("https://", "no host at all"),
]


class TestTheConfigBoundary:
    @pytest.mark.parametrize("url", ACCEPTED)
    def test_the_real_paper_endpoint_is_ACCEPTED(self, url):
        """Half of a gate is not refusing the wrong thing; it is admitting the
        right one. Without these the allowlist could pass by refusing all."""
        a_config(url).assert_paper()

    @pytest.mark.parametrize("url,why", REFUSED)
    def test_everything_else_is_REFUSED(self, url, why):
        with pytest.raises(CFG.LiveEndpointRefused):
            a_config(url).assert_paper()

    def test_from_env_refuses_at_construction(self):
        with pytest.raises(CFG.LiveEndpointRefused):
            CFG.SentinelConfig.from_env({"ALPACA_BASE_URL":
                                         "https://api.alpaca.markets"})

    def test_the_default_is_the_paper_endpoint(self):
        cfg = CFG.SentinelConfig.from_env({})
        assert cfg.base_url == CFG.DEFAULT_BASE_URL
        assert cfg.is_paper_endpoint

    def test_there_is_no_OVERRIDE(self):
        """Any env var that could grant a live mandate is the defect. Scanning
        the source rather than trying names: an allowlist of names would miss
        the one somebody adds."""
        src = (REPO / "sentinel" / "config.py").read_text()
        # `def assert_paper(self)`, NOT `def assert_paper` — the latter is a
        # prefix of `def assert_paper_url`, matched it at the top of the file,
        # and swept `from_env` into the slice. The guard then failed on the
        # env reads that are supposed to be there.
        start = src.index("def assert_paper(self)")
        gate = src[start:src.index("def assert_credentials", start)]
        gate = "\n".join(l for l in gate.splitlines()
                         if not l.strip().startswith("#"))
        assert "PAPER_HOSTS" in gate or "is_paper_endpoint" in gate, (
            "the slice missed the gate body, so this proves nothing")
        assert "environ" not in gate and "getenv" not in gate, (
            "the paper gate reads the environment, so something can turn it off")


class TestTheAdapterBoundary:
    """`AlpacaExecutionBroker` takes a bare `base_url` and holds the
    credentials. Config-level protection does not reach it."""

    def test_the_adapter_refuses_a_non_paper_url(self):
        with pytest.raises(CFG.LiveEndpointRefused):
            AlpacaExecutionBroker(api_key="k", secret_key="s",
                                  base_url="https://api.alpaca.markets")

    @pytest.mark.parametrize("url,why", REFUSED)
    def test_the_adapter_applies_the_SAME_allowlist(self, url, why):
        with pytest.raises(CFG.LiveEndpointRefused):
            AlpacaExecutionBroker(api_key="k", secret_key="s", base_url=url)

    def test_the_adapter_still_constructs_for_PAPER(self):
        b = AlpacaExecutionBroker(api_key="k", secret_key="s", base_url=PAPER)
        assert b.base_url == PAPER

    def test_both_boundaries_call_ONE_predicate(self):
        """Two copies of an allowlist drift, and the copy that drifts is the
        one nobody is reading when it matters."""
        src = (REPO / "sentinel" / "execution" / "alpaca.py").read_text()
        assert "assert_paper_url" in src
        assert "PAPER_HOSTS" not in src, (
            "the adapter restates the allowlist instead of importing it")


class TestTheDenylistIsNoLongerTheGate:
    def test_is_live_endpoint_still_exists_for_the_RECORD(self):
        """Kept deliberately — the panel and the audit record want to say WHY
        something was refused. It is simply not the decision any more."""
        assert a_config("https://api.alpaca.markets").is_live_endpoint
        assert not a_config("https://evil.example").is_live_endpoint

    def test_a_host_absent_from_the_denylist_is_still_refused(self):
        """The finding, stated as one assertion: not-live is not the same as
        allowed."""
        cfg = a_config("https://api.alpaca.markets.evil.example")
        assert not cfg.is_live_endpoint          # the denylist says fine
        with pytest.raises(CFG.LiveEndpointRefused):
            cfg.assert_paper()                   # the allowlist does not
