"""Collector service integration: real mainnet fixtures, LIVE/FIXTURE parity, errors and KYT compatibility."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from collector.capture import ReplayRpc
from collector.errors import CollectionError, FixtureNotFound, ProviderError
from collector.labels import LabelDataset
from collector.service import Collector
from compliance_contracts.runtime import ContractViolation, instant, link_evaluation, validate
from kyt_engine import Detector

REAL_ROOT = Path(__file__).resolve().parents[2] / "services" / "collector" / "fixtures"
REAL_FIXTURES = ["mainnet-normal-wallet", "mainnet-ofac-sdn-exact", "mainnet-busy-wallet-partial", "mainnet-rapid-fan-out"]
NORMAL_ADDRESS = "6UuyGCx5J5WjL1oiMnWAEoqGX6iNM2TcG6DUtjyr8NTA"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
COLLECTOR_ENV = ("COLLECTOR_MAX_TRANSACTIONS", "COLLECTOR_LABEL_DATASET", "COLLECTOR_FIXTURE_ROOTS",
                 "COLLECTOR_FETCH_WORKERS", "COLLECTOR_TIME_BUDGET_SECONDS", "COLLECTOR_MAX_TOKEN_ACCOUNTS",
                 "SOLANA_RPC_URL", "SOLANA_RPC_PROVIDER", "SOLANA_RPC_API_KEY", "SOLANA_RPC_API_KEY_HEADER",
                 "SOLANA_RPC_TIMEOUT", "SOLANA_RPC_MAX_TX_VERSION")


def load(fixture_id, name):
    return json.loads((REAL_ROOT / fixture_id / name).read_text(encoding="utf-8"))


def label_dataset(source="TEST_FIXTURE", entries=(), version="1.0.0", fetched_at="2026-11-10T00:00:00Z"):
    return LabelDataset.from_mapping({
        "source": source, "version": version, "fetchedAt": fetched_at, "reference": None,
        "entries": list(entries),
    })


def live_request(address, from_time, to_time, max_transactions=50, request_id="svc-test"):
    return {
        "requestId": request_id, "address": address, "network": "mainnet-beta", "mode": "LIVE",
        "scope": {"fromTime": from_time, "toTime": to_time, "maxTransactions": max_transactions},
    }


class FakeRpc:
    """Minimal RPC double: fixed signature history and optional provider failures."""

    def __init__(self, signatures=(), slot=1000, slot_error=None):
        self._signatures = list(signatures)
        self._slot = slot
        self._slot_error = slot_error

    def get_slot(self, commitment="finalized"):
        if self._slot_error is not None:
            raise self._slot_error
        return self._slot

    def get_token_accounts_by_owner(self, owner, program_id, commitment="finalized"):
        return []

    def get_signatures_for_address(self, address, before=None, limit=1000, commitment="finalized"):
        return list(self._signatures) if before is None else []

    def get_transaction(self, signature, commitment="finalized"):
        raise AssertionError("no transaction should be fetched for this history")


class ReplayWithFailure:
    """Replays a recording but fails the RPC call for one transaction signature."""

    def __init__(self, calls, failing_signature):
        self._replay = ReplayRpc(calls)
        self._failing = failing_signature

    def get_transaction(self, signature, commitment="finalized"):
        if signature == self._failing:
            raise ProviderError("Solana RPC unavailable", retryable=True)
        return self._replay.get_transaction(signature, commitment=commitment)

    def __getattr__(self, name):
        return getattr(self._replay, name)


@pytest.fixture(autouse=True)
def clean_collector_env(monkeypatch):
    for name in COLLECTOR_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("fixture_id", REAL_FIXTURES)
def test_real_capture_is_reproducible_from_raw_rpc_recording(fixture_id):
    stored = load(fixture_id, "snapshot.json")
    recording = load(fixture_id, "rpc-recording.json")
    request = load(fixture_id, "collection-request.json")
    live = {key: value for key, value in request.items() if key != "fixtureId"}
    live["mode"] = "LIVE"

    labels = label_dataset(
        source=stored["labelDataset"]["source"],
        version=stored["labelDataset"]["version"],
        fetched_at=stored["labelDataset"]["fetchedAt"],
        entries=[{"address": label["address"], "type": label["type"], "referenceId": label["referenceId"]}
                 for label in stored["labels"]],
    )
    collector = Collector(
        rpc_factory=lambda: ReplayRpc(recording["calls"]),
        label_loader=lambda: labels,
        provider_name=stored["dataProvenance"]["source"],
        clock=lambda: instant(recording["collectedAt"]),
        env={},
    )
    result = collector.collect(live)

    expected = copy.deepcopy(stored)
    expected["mode"] = "LIVE"
    expected["dataProvenance"]["reference"] = None
    assert result == expected


@pytest.mark.parametrize("fixture_id", REAL_FIXTURES)
def test_fixture_mode_returns_stored_snapshot(fixture_id):
    request = load(fixture_id, "collection-request.json")
    stored = load(fixture_id, "snapshot.json")

    result = Collector().collect(request)

    assert result["requestId"] == request["requestId"] == stored["requestId"]
    assert result == stored
    validate("collector", "KYTDataSnapshot", result)


@pytest.mark.parametrize("fixture_id", REAL_FIXTURES)
def test_live_and_fixture_outputs_share_key_structure(fixture_id):
    stored = load(fixture_id, "snapshot.json")
    recording = load(fixture_id, "rpc-recording.json")
    request = load(fixture_id, "collection-request.json")
    live_req = {key: value for key, value in request.items() if key != "fixtureId"}
    live_req["mode"] = "LIVE"
    labels = label_dataset(
        source=stored["labelDataset"]["source"], version=stored["labelDataset"]["version"],
        fetched_at=stored["labelDataset"]["fetchedAt"],
        entries=[{"address": l["address"], "type": l["type"], "referenceId": l["referenceId"]} for l in stored["labels"]],
    )
    live = Collector(
        rpc_factory=lambda: ReplayRpc(recording["calls"]), label_loader=lambda: labels,
        provider_name=stored["dataProvenance"]["source"], clock=lambda: instant(recording["collectedAt"]), env={},
    ).collect(live_req)
    fixture = Collector().collect(request)

    assert set(live) == set(fixture)
    assert set(live["coverage"]) == set(fixture["coverage"])
    assert set(live["labelDataset"]) == set(fixture["labelDataset"])
    assert set(live["dataProvenance"]) == set(fixture["dataProvenance"])
    assert len(live["transfers"]) == len(fixture["transfers"])
    assert len(live["labels"]) == len(fixture["labels"])
    for live_row, fixture_row in zip(live["transfers"], fixture["transfers"]):
        assert set(live_row) == set(fixture_row)
    for live_label, fixture_label in zip(live["labels"], fixture["labels"]):
        assert set(live_label) == set(fixture_label)


def test_max_transactions_above_collector_cap_is_invalid_request():
    request = load("mainnet-normal-wallet", "collection-request.json")
    request["scope"]["maxTransactions"] = 11

    with pytest.raises(ContractViolation) as info:
        Collector(max_transactions=10).collect(request)

    assert info.value.code == "INVALID_REQUEST"


def test_live_without_rpc_url_is_service_unavailable():
    collector = Collector(
        label_loader=lambda: label_dataset(),
        clock=lambda: NOW,
        env={},
    )
    request = live_request(NORMAL_ADDRESS, "2026-10-01T00:00:00Z", "2026-11-10T00:00:00Z")

    with pytest.raises(CollectionError) as info:
        collector.collect(request)

    assert info.value.status == 503
    assert info.value.retryable is False


def test_missing_label_dataset_fails_before_rpc_is_touched(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    calls = []

    def rpc_factory():
        calls.append("rpc")
        return FakeRpc()

    collector = Collector(rpc_factory=rpc_factory, clock=lambda: NOW,
                          env={"COLLECTOR_LABEL_DATASET": str(missing)})
    request = live_request(NORMAL_ADDRESS, "2026-10-01T00:00:00Z", "2026-11-10T00:00:00Z")

    with pytest.raises(CollectionError) as info:
        collector.collect(request)

    assert info.value.status == 503
    assert calls == []


def test_unknown_fixture_id_is_not_found():
    request = load("mainnet-normal-wallet", "collection-request.json")
    request["fixtureId"] = "no-such-fixture"

    with pytest.raises(FixtureNotFound) as info:
        Collector().collect(request)

    assert info.value.status == 404
    assert info.value.code == "NOT_FOUND"


def test_missing_scope_is_contract_violation():
    request = load("mainnet-normal-wallet", "collection-request.json")
    del request["scope"]

    with pytest.raises(ContractViolation):
        Collector().collect(request)


def test_live_request_with_fixture_id_is_contract_violation():
    request = live_request(NORMAL_ADDRESS, "2026-10-01T00:00:00Z", "2026-11-10T00:00:00Z")
    request["fixtureId"] = "mainnet-normal-wallet"

    with pytest.raises(ContractViolation):
        Collector(label_loader=lambda: label_dataset(), rpc_factory=lambda: FakeRpc(),
                  clock=lambda: NOW, env={}).collect(request)


def test_provider_error_propagates_as_retryable():
    collector = Collector(
        rpc_factory=lambda: FakeRpc(slot_error=ProviderError("Solana RPC unavailable", retryable=True)),
        label_loader=lambda: label_dataset(),
        clock=lambda: NOW,
        env={"SOLANA_RPC_URL": "https://rpc.invalid/unused"},
    )
    request = live_request(NORMAL_ADDRESS, "2026-10-01T00:00:00Z", "2026-11-10T00:00:00Z")

    with pytest.raises(ProviderError) as info:
        collector.collect(request)

    assert info.value.retryable is True


def test_empty_live_history_is_complete_with_zero_transactions():
    collector = Collector(
        rpc_factory=lambda: FakeRpc(signatures=[], slot=1000),
        label_loader=lambda: label_dataset(),
        clock=lambda: NOW,
        env={},
    )
    request = live_request(NORMAL_ADDRESS, "2026-10-01T00:00:00Z", "2026-11-10T00:00:00Z")

    result = collector.collect(request)

    assert result["coverage"]["status"] == "COMPLETE"
    assert result["coverage"]["reasons"] == []
    assert result["coverage"]["transactionCount"] == 0
    assert result["coverage"]["transferCount"] == 0
    assert result["coverage"]["reachedTimeBoundary"] is True
    assert result["transfers"] == []
    assert result["labels"] == []


def test_failed_transaction_fetch_is_partial_not_empty():
    recording = load("mainnet-normal-wallet", "rpc-recording.json")
    stored = load("mainnet-normal-wallet", "snapshot.json")
    failing = stored["transfers"][0]["signature"]
    request = live_request(NORMAL_ADDRESS, "2026-10-01T00:00:00Z", "2026-11-10T00:00:00Z", max_transactions=50)

    result = Collector(
        rpc_factory=lambda: ReplayWithFailure(recording["calls"], failing),
        label_loader=lambda: label_dataset(),
        clock=lambda: instant(recording["collectedAt"]),
        env={},
    ).collect(request)

    assert result["coverage"]["status"] == "PARTIAL"
    assert "TRANSACTION_FETCH_FAILED" in result["coverage"]["reasons"]
    assert failing not in {row["signature"] for row in result["transfers"]}
    assert result["transfers"], "other transactions must still be normalized"
    validate("collector", "KYTDataSnapshot", result)


# --- KYT compatibility -------------------------------------------------------------------------

@pytest.mark.parametrize("fixture_id", REAL_FIXTURES)
def test_real_snapshots_evaluate_and_link_back_to_kyt(fixture_id):
    snapshot = load(fixture_id, "snapshot.json")

    evaluation = Detector().evaluate({"requestId": "x", "snapshot": snapshot, "rulesetVersion": "1.0.0"})

    link_evaluation(snapshot, evaluation)


def test_exact_ofac_match_is_detected():
    snapshot = load("mainnet-ofac-sdn-exact", "snapshot.json")

    evaluation = Detector().evaluate({"requestId": "x", "snapshot": snapshot, "rulesetVersion": "1.0.0"})

    assert "SANCTION_EXACT" in {rule["ruleId"] for rule in evaluation["detectedRules"]}


def test_real_fan_out_pattern_is_detected_on_complete_data():
    snapshot = load("mainnet-rapid-fan-out", "snapshot.json")

    evaluation = Detector().evaluate({"requestId": "x", "snapshot": snapshot, "rulesetVersion": "1.0.0"})

    assert snapshot["coverage"]["status"] == "COMPLETE"
    assert [rule["ruleId"] for rule in evaluation["detectedRules"]] == ["RAPID_FAN_OUT"]
    assert evaluation["riskLevel"] == "MEDIUM"


def test_busy_wallet_includes_incoming_token_account_transfers():
    """Regression: incoming SPL transfers that only list the wallet's token account must be collected.

    The replay test above proves this snapshot is what the current pipeline produces from the raw
    recording, so a pipeline without token-account scanning fails there and here.
    """
    snapshot = load("mainnet-busy-wallet-partial", "snapshot.json")
    address = snapshot["address"]

    incoming = [t for t in snapshot["transfers"] if t["toAddress"] == address and t["destinationAccount"] != address]

    assert incoming, "incoming token-account transfers are missing"


def test_partial_snapshot_has_no_risk_score():
    snapshot = load("mainnet-busy-wallet-partial", "snapshot.json")

    evaluation = Detector().evaluate({"requestId": "x", "snapshot": snapshot, "rulesetVersion": "1.0.0"})

    assert snapshot["coverage"]["status"] == "PARTIAL"
    assert evaluation["riskScore"] is None


def test_window_reaching_into_the_future_is_not_complete():
    """Regression: an empty history up to 'now' does not cover a toTime that has not happened yet."""
    request = live_request(NORMAL_ADDRESS, "2026-11-10T00:00:00Z", "2026-11-20T00:00:00Z")

    result = Collector(rpc_factory=lambda: FakeRpc(), label_loader=label_dataset, clock=lambda: NOW,
                       env={}).collect(request)

    assert result["coverage"]["status"] == "PARTIAL"
    assert result["coverage"]["reasons"] == ["TIME_BOUNDARY_NOT_REACHED"]
    assert result["coverage"]["reachedTimeBoundary"] is False
    validate("collector", "KYTDataSnapshot", result)


def test_explicit_max_transactions_is_not_replaced_by_env():
    with pytest.raises(ValueError):
        Collector(max_transactions=0, env={"COLLECTOR_MAX_TRANSACTIONS": "5"})
