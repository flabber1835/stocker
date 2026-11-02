"""Legacy PAPER keys and durable LIVE environment separation."""
import hashlib
import json

from sentinel.binding import AccountBinding
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.trading_environment import TradingEnvironment


ACCOUNT = "11111111-1111-1111-1111-111111111111"


def identity(broker="alpaca"):
    return DeploymentIdentity("appliance", broker, ACCOUNT, 1)


def test_historical_paper_payload_and_key_remain_byte_identical():
    expected = {"v": 1, "deployment_id": "appliance", "broker": "alpaca",
                "broker_account_id": ACCOUNT, "takeover_epoch": 1,
                "plan_id": "plan-1", "security_id": "SEC", "revision": 0}
    command = CommandIdentity(identity(), "plan-1", "SEC")
    assert command.payload == expected
    expected_bytes = json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
    assert command.client_key == "sntl-" + hashlib.sha256(expected_bytes).hexdigest()[:20]
    assert identity().to_dict() == {name: expected[name] for name in (
        "deployment_id", "broker", "broker_account_id", "takeover_epoch")}


def test_live_key_v2_is_reconstructed_from_existing_durable_namespace():
    binding = AccountBinding("appliance", "alpaca-live", ACCOUNT, 1)
    command = CommandIdentity(binding.identity, "plan-1", "SEC")
    assert binding.trading_environment is TradingEnvironment.LIVE
    assert binding.trading_base_url == "https://api.alpaca.markets"
    assert command.payload["v"] == 2
    assert command.payload["environment"] == "ALPACA_LIVE"
    assert command.payload["base_url"] == "https://api.alpaca.markets"
    assert command.client_key != CommandIdentity(identity(), "plan-1", "SEC").client_key
    restored = DeploymentIdentity(**binding.identity.to_dict())
    assert CommandIdentity(restored, "plan-1", "SEC").client_key == command.client_key
    assert command.superseding().payload["environment"] == "ALPACA_LIVE"


def test_same_uuid_in_paper_and_live_never_matches():
    paper, live = identity(), identity("alpaca-live")
    assert not paper.matches_account(live)
    assert not live.matches_account(paper)
    assert live.matches_account({"broker": "alpaca-live", "account_id": ACCOUNT})
    assert not live.matches_account({"broker": "alpaca-live", "account_id": ACCOUNT,
                                     "environment": "ALPACA_PAPER"})
    assert not paper.matches_account({"broker": "alpaca", "account_id": ACCOUNT,
                                      "base_url": "https://api.alpaca.markets"})


def test_simulator_serialization_is_not_rekeyed_by_live_support():
    command = CommandIdentity(identity("sim"), "plan-1", "SEC")
    assert command.payload["v"] == 1
    assert "environment" not in command.payload
    assert identity("sim").trading_environment is None
