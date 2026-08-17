from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if not SCRIPTS.is_dir():
    SCRIPTS = ROOT / "repo" / "scripts"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    sys.modules[name] = module
    return module


core = _load("sentinel_autonomous_deploy", SCRIPTS / "sentinel_autonomous_deploy.py")
_load("sentinel_autonomous_deploy_driver", SCRIPTS / "sentinel_autonomous_deploy_driver.py")
bootstrap = _load(
    "sentinel_autonomous_deploy_bootstrap",
    SCRIPTS / "sentinel_autonomous_deploy_bootstrap.py")


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def read(self):
        return self.payload


def _object(tmp_path):
    cfg = SimpleNamespace(account_id="PA3UVTMJYYGM")
    runner = SimpleNamespace(env={
        "ALPACA_API_KEY": "paper-key",
        "ALPACA_SECRET_KEY": "paper-secret",
    })
    obj = bootstrap.BootstrapDeploy(cfg, runner, tmp_path)
    obj.phase = lambda _text: None
    return obj


def test_redeploy_preflight_allows_invested_owned_account(monkeypatch, tmp_path):
    # Cash and buying power intentionally differ materially: a deployed Sentinel
    # account can own positions. Flatness belongs only to ADMIN_BIND_EMPTY.
    payload = {
        "id": "uuid-1",
        "account_number": "PA3UVTMJYYGM",
        "status": "ACTIVE",
        "trading_blocked": False,
        "account_blocked": False,
        "trade_suspended_by_user": False,
        "equity": "123456.78",
        "cash": "23456.78",
        "buying_power": "46891.22",
        "multiplier": "2",
    }
    monkeypatch.setattr(
        bootstrap.urllib.request, "urlopen",
        lambda *_args, **_kwargs: Response(payload))
    obj = _object(tmp_path)

    obj.read_paper_account()

    assert str(obj.account_equity) == "123456.78"


def test_redeploy_preflight_still_refuses_wrong_account(monkeypatch, tmp_path):
    payload = {
        "id": "uuid-2",
        "account_number": "OTHER",
        "status": "ACTIVE",
        "trading_blocked": False,
        "account_blocked": False,
        "trade_suspended_by_user": False,
        "equity": "100000",
        "cash": "100000",
        "buying_power": "100000",
    }
    monkeypatch.setattr(
        bootstrap.urllib.request, "urlopen",
        lambda *_args, **_kwargs: Response(payload))
    obj = _object(tmp_path)

    with pytest.raises(core.DeployRefused, match="different paper account"):
        obj.read_paper_account()


def test_redeploy_preflight_still_refuses_broker_block(monkeypatch, tmp_path):
    payload = {
        "id": "uuid-1",
        "account_number": "PA3UVTMJYYGM",
        "status": "ACTIVE",
        "trading_blocked": True,
        "account_blocked": False,
        "trade_suspended_by_user": False,
        "equity": "100000",
        "cash": "50000",
        "buying_power": "100000",
    }
    monkeypatch.setattr(
        bootstrap.urllib.request, "urlopen",
        lambda *_args, **_kwargs: Response(payload))
    obj = _object(tmp_path)

    with pytest.raises(core.DeployRefused, match="trading_blocked"):
        obj.read_paper_account()
