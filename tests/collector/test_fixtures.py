import copy
import json
from pathlib import Path

import pytest

from collector import fixtures
from collector.errors import CollectionError, FixtureNotFound
from collector.fixtures import FixtureStore, apply_request
from compliance_contracts.runtime import validate

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_FIXTURES = REPO_ROOT / "contracts" / "fixtures"
COLLECTION_REQUESTS = sorted(CONTRACT_FIXTURES.glob("*/collection-request.json"))
ADDRESS = "8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def request(fixture_id, **scope):
    base = load_json(CONTRACT_FIXTURES / fixture_id / "collection-request.json")
    base["scope"] = {**base["scope"], **scope}
    return base


def stored(fixture_id):
    return load_json(CONTRACT_FIXTURES / fixture_id / "snapshot.json")


def collect(fixture_id, **scope):
    req = request(fixture_id, **scope)
    result = apply_request(FixtureStore().load(req["fixtureId"]), req)
    validate("collector", "KYTDataSnapshot", result)
    return result


@pytest.fixture(autouse=True)
def no_fixture_env(monkeypatch):
    monkeypatch.delenv(fixtures.ROOTS_ENV, raising=False)


@pytest.mark.parametrize("path", COLLECTION_REQUESTS, ids=lambda p: p.parent.name)
def test_contract_fixture_round_trip_equals_stored_snapshot(path):
    req = load_json(path)
    result = apply_request(FixtureStore().load(req["fixtureId"]), req)
    validate("collector", "KYTDataSnapshot", result)
    expected = stored(req["fixtureId"])
    expected["requestId"] = req["requestId"]
    assert result == expected


def test_contract_fixtures_are_discovered():
    assert COLLECTION_REQUESTS, "no collection-request.json fixtures found"


def test_list_reports_contract_fixtures_with_metadata():
    entries = {row["fixtureId"]: row for row in FixtureStore().list()}
    assert entries["normal"]["address"] == ADDRESS
    assert entries["normal"]["dataType"] == "SYNTHETIC"
    assert entries["normal"]["path"].endswith("contracts/fixtures/normal/snapshot.json")


def test_load_returns_independent_copy():
    store = FixtureStore()
    first = store.load("normal")
    first["transfers"].clear()
    assert store.load("normal") == stored("normal")


@pytest.mark.parametrize("fixture_id", ["missing", "../x", "a/b", "..", ".", "", ".hidden", "x" * 65, "a b"])
def test_invalid_or_unknown_fixture_ids_are_not_found(fixture_id):
    with pytest.raises(FixtureNotFound) as info:
        FixtureStore().load(fixture_id)
    assert info.value.code == "NOT_FOUND"
    assert info.value.status == 404


def test_address_mismatch_is_conflict():
    req = request("normal")
    req["address"] = "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"
    with pytest.raises(CollectionError) as info:
        apply_request(stored("normal"), req)
    assert info.value.code == "CONFLICT"
    assert info.value.status == 409
    assert info.value.retryable is False


def test_same_scope_only_changes_request_id():
    req = request("warn")
    result = apply_request(stored("warn"), req)
    expected = stored("warn")
    expected["requestId"] = req["requestId"]
    assert result == expected


def test_input_snapshot_is_not_modified():
    snapshot = stored("warn")
    before = copy.deepcopy(snapshot)
    apply_request(snapshot, request("warn", toTime="2026-11-01T00:01:30Z"))
    assert snapshot == before


def test_narrower_window_inside_fixture_filters_transfers_and_stays_complete():
    result = collect("warn", toTime="2026-11-01T00:01:30Z")
    assert [t["timestamp"] for t in result["transfers"]] == ["2026-11-01T00:00:00Z", "2026-11-01T00:01:00Z"]
    assert result["coverage"]["status"] == "COMPLETE"
    assert result["coverage"]["reasons"] == []
    assert result["coverage"]["reachedTimeBoundary"] is True
    assert result["coverage"]["transferCount"] == 2
    assert result["coverage"]["transactionCount"] == 2
    assert result["coverage"]["fromTime"] == "2026-11-01T00:00:00Z"
    assert result["coverage"]["toTime"] == "2026-11-01T00:01:30Z"
    assert result["snapshotId"] != stored("warn")["snapshotId"]


def test_narrower_window_keeps_labels_for_subject_only_when_related():
    result = collect("sanctioned", toTime="2026-11-01T00:00:30Z")
    assert [label["referenceId"] for label in result["labels"]] == ["synthetic-sanction-001"]


def test_narrower_window_that_excludes_all_transfers_is_empty_complete():
    result = collect("warn", fromTime="2026-11-01T00:10:00Z", toTime="2026-11-01T00:20:00Z")
    assert result["transfers"] == []
    assert result["coverage"]["status"] == "COMPLETE"
    assert result["coverage"]["transactionCount"] == 0


def test_wider_window_reports_time_boundary_not_reached():
    result = collect("normal", fromTime="2026-10-31T00:00:00Z")
    assert result["coverage"]["status"] == "PARTIAL"
    assert result["coverage"]["reasons"] == ["TIME_BOUNDARY_NOT_REACHED"]
    assert result["coverage"]["reachedTimeBoundary"] is False
    assert len(result["transfers"]) == 1


def test_window_starting_mid_fixture_range():
    result = collect("warn", toTime="2026-11-01T00:01:30Z", fromTime="2026-11-01T00:00:30Z")
    assert result["coverage"]["status"] == "COMPLETE"
    assert [t["timestamp"] for t in result["transfers"]] == ["2026-11-01T00:01:00Z"]
    wider = collect("warn", fromTime="2026-10-31T23:00:00Z")
    assert wider["coverage"]["status"] == "PARTIAL"
    assert "TIME_BOUNDARY_NOT_REACHED" in wider["coverage"]["reasons"]


def test_small_max_transactions_keeps_newest_and_reports_limit():
    result = collect("repeat", maxTransactions=2)
    assert result["coverage"]["status"] == "PARTIAL"
    assert result["coverage"]["reasons"] == ["TRANSACTION_LIMIT_REACHED"]
    assert result["coverage"]["reachedTimeBoundary"] is False
    assert result["coverage"]["transactionCount"] == 2
    assert result["coverage"]["transferCount"] == 2
    assert sorted(t["slot"] for t in result["transfers"]) == [106, 107]


def test_max_transactions_at_limit_is_not_partial():
    result = collect("repeat", maxTransactions=3)
    assert result["coverage"]["status"] == "COMPLETE"
    assert result["coverage"]["transactionCount"] == 3


def test_limit_applies_to_fixture_already_partial_by_limit():
    result = collect("partial", maxTransactions=1)
    assert result["coverage"]["status"] == "PARTIAL"
    assert result["coverage"]["reasons"] == ["TRANSACTION_LIMIT_REACHED"]
    assert result["coverage"]["transactionCount"] == 1


def test_missing_time_stays_partial_when_window_is_narrower():
    result = collect("missing-time", toTime="2026-11-01T12:00:00Z")
    assert result["transfers"] == []
    assert result["coverage"]["status"] == "PARTIAL"
    assert result["coverage"]["reasons"] == ["TIMESTAMP_UNAVAILABLE"]
    assert result["coverage"]["reachedTimeBoundary"] is True


def test_missing_time_transfer_kept_when_window_covers_fixture():
    result = collect("missing-time", fromTime="2026-10-31T00:00:00Z", toTime="2026-11-03T00:00:00Z")
    assert len(result["transfers"]) == 1
    assert result["transfers"][0]["timestamp"] is None
    assert result["coverage"]["reasons"] == ["TIMESTAMP_UNAVAILABLE", "TIME_BOUNDARY_NOT_REACHED"]


def test_unresolved_owner_is_dropped_when_its_transfer_leaves_the_window():
    result = collect("unresolved", toTime="2026-11-01T00:00:00Z", fromTime="2026-10-31T00:00:00Z")
    assert result["transfers"] == []
    assert result["coverage"]["reasons"] == ["TIME_BOUNDARY_NOT_REACHED"]


def test_unresolved_owner_reason_kept_when_transfer_remains():
    result = collect("unresolved", fromTime="2026-11-01T00:00:00Z", toTime="2026-11-01T06:00:00Z")
    assert result["coverage"]["reasons"] == ["OWNER_UNRESOLVED"]
    assert result["coverage"]["status"] == "PARTIAL"
    assert result["coverage"]["reachedTimeBoundary"] is True


def test_snapshot_id_depends_on_scope():
    first = collect("warn", toTime="2026-11-01T00:01:30Z")
    second = collect("warn", toTime="2026-11-01T00:01:31Z")
    assert first["snapshotId"] != second["snapshotId"]
    assert first["snapshotId"] == collect("warn", toTime="2026-11-01T00:01:30Z")["snapshotId"]


def test_custom_roots_from_env_override_defaults(tmp_path, monkeypatch):
    source = CONTRACT_FIXTURES / "normal" / "snapshot.json"
    target = tmp_path / "custom" / "normal"
    target.mkdir(parents=True)
    (target / "snapshot.json").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv(fixtures.ROOTS_ENV, str(tmp_path / "custom"))
    store = FixtureStore()
    assert [row["fixtureId"] for row in store.list()] == ["normal"]
    with pytest.raises(FixtureNotFound):
        store.load("warn")


def test_earlier_root_shadows_later_root(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    for root, marker in ((first, "first"), (second, "second")):
        (root / "shared").mkdir(parents=True)
        (root / "shared" / "snapshot.json").write_text(
            json.dumps({**stored("normal"), "snapshotId": marker}), encoding="utf-8")
    store = FixtureStore([first, second])
    assert store.load("shared")["snapshotId"] == "first"
    assert [row["path"] for row in store.list()] == [str(first / "shared" / "snapshot.json")]


def test_missing_roots_list_nothing(tmp_path):
    assert FixtureStore([tmp_path / "absent"]).list() == []


def test_snapshot_outside_root_via_symlink_is_not_found(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside" / "escape"
    outside.mkdir(parents=True)
    (outside / "snapshot.json").write_text(json.dumps(stored("normal")), encoding="utf-8")
    root.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(FixtureNotFound):
        FixtureStore([root]).load("escape")


def test_unreadable_snapshot_is_internal_error(tmp_path):
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "snapshot.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(CollectionError) as info:
        FixtureStore([tmp_path]).load("broken")
    assert info.value.code == "INTERNAL_ERROR"
    assert info.value.status == 500


def test_transactions_without_transfers_count_toward_the_limit():
    """Regression: the OFAC fixture has 5 transactions and no transfers; a cap below 5 must be reported."""
    store = FixtureStore()
    snapshot = store.load("mainnet-ofac-sdn-exact")
    scope = {"fromTime": snapshot["coverage"]["fromTime"], "toTime": snapshot["coverage"]["toTime"], "maxTransactions": 3}
    request = {"requestId": "cap-3", "address": snapshot["address"], "network": "mainnet-beta",
               "mode": "FIXTURE", "fixtureId": "mainnet-ofac-sdn-exact", "scope": scope}

    result = apply_request(snapshot, request)

    assert result["coverage"]["status"] == "PARTIAL"
    assert "TRANSACTION_LIMIT_REACHED" in result["coverage"]["reasons"]
    assert result["coverage"]["transactionCount"] == 3
    assert result["coverage"]["reachedTimeBoundary"] is False
    assert [label["referenceId"] for label in result["labels"]] == ["OFAC-SDN-56360"]  # exact match survives
    validate("collector", "KYTDataSnapshot", result)


def test_transaction_sidecar_gives_exact_counts_for_a_narrower_window():
    """The OFAC fixture's 5 transactions have no transfers; the sidecar still places them in time."""
    store = FixtureStore()
    snapshot = store.load("mainnet-ofac-sdn-exact")
    request = {"requestId": "narrow", "address": snapshot["address"], "network": "mainnet-beta", "mode": "FIXTURE",
               "fixtureId": "mainnet-ofac-sdn-exact",
               "scope": {"fromTime": "2026-11-06T00:00:00Z", "toTime": "2026-11-07T00:00:00Z", "maxTransactions": 50}}

    result = apply_request(snapshot, request, store.load_transactions("mainnet-ofac-sdn-exact"))

    assert result["coverage"]["transactionCount"] == 3  # three transactions on 2026-11-06
    assert result["coverage"]["status"] == "COMPLETE"
    validate("collector", "KYTDataSnapshot", result)

    request["scope"]["maxTransactions"] = 2
    limited = apply_request(snapshot, request, store.load_transactions("mainnet-ofac-sdn-exact"))
    assert limited["coverage"]["transactionCount"] == 2
    assert "TRANSACTION_LIMIT_REACHED" in limited["coverage"]["reasons"]


def test_synthetic_fixtures_have_no_transaction_sidecar():
    assert FixtureStore().load_transactions("normal") is None
