import subprocess
from types import SimpleNamespace

import pytest

import sentinel_go_process as owned


@pytest.mark.parametrize("interrupt", [False, True])
def test_exact_owned_container_cleanup_on_completion_and_interrupt(monkeypatch, interrupt):
    calls = []
    monkeypatch.setattr(owned.subprocess, "run", lambda argv, **kw:
                        calls.append(argv) or SimpleNamespace(returncode=0))
    command = ["docker", "compose", "-f", "compose.yml", "run", "--rm", "sentinel"]
    try:
        with owned.owned_command(command) as owner:
            name = owner["command"][owner["command"].index("--name") + 1]
            assert name.startswith("sentinel-go-owned-")
            if interrupt:
                raise KeyboardInterrupt()
    except KeyboardInterrupt:
        assert interrupt
    assert calls == [["docker", "rm", "-f", name]]
    assert "--name" not in command


def test_cleanup_cannot_claim_success_when_docker_is_unavailable(monkeypatch):
    monkeypatch.setattr(owned.subprocess, "run", lambda *a, **kw:
                        SimpleNamespace(returncode=1, stdout=""))
    with pytest.raises(RuntimeError, match="could not verify cleanup"):
        with owned.owned_command(["docker", "run", "--rm", "test"]):
            pass
