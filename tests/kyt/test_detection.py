from copy import deepcopy
from datetime import datetime, timedelta, timezone
import random
import socket
import sqlite3

import pytest

from compliance_contracts.runtime import ContractViolation, ROOT, read_json, validate
from kyt_engine import Detector
from kyt_engine.engine import _temporal_matches

SCENARIOS = sorted(path.parent.name for path in (ROOT / "fixtures").glob("*/evaluation-request.json"))


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_contract_golden_outputs(detector, fixture_json, scenario):
    actual = detector.evaluate(fixture_json(scenario + "/evaluation-request.json"))
    assert actual == fixture_json(scenario + "/evaluation.json")
    validate("kyt", "KYTEvaluation", actual)


def test_exact_match_does_not_require_a_transaction(detector, fixture_json, sync_snapshot):
    request = fixture_json("sanctioned/evaluation-request.json")
    request["snapshot"]["transfers"] = []
    result = detector.evaluate(sync_snapshot(request))
    assert result["riskScore"] == 100
    assert result["detectedRules"][0]["ruleId"] == "SANCTION_EXACT"
    assert result["evidences"][0]["transactionSignatures"] == []


@pytest.mark.parametrize("incoming", [True, False])
def test_direct_flow_is_bidirectional(detector, fixture_json, incoming):
    request = fixture_json("direct-flow/evaluation-request.json")
    if not incoming:
        row = request["snapshot"]["transfers"][0]
        row["fromAddress"], row["toAddress"] = row["toAddress"], row["fromAddress"]
        row["sourceAccount"], row["destinationAccount"] = row["destinationAccount"], row["sourceAccount"]
    result = detector.evaluate(request)
    assert result["riskScore"] == 80
    assert [r["ruleId"] for r in result["detectedRules"]] == ["SANCTION_DIRECT_FLOW"]


def test_token_account_label_matches_even_if_owner_unknown(detector, fixture_json):
    request = fixture_json("unresolved/evaluation-request.json")
    snapshot = request["snapshot"]
    label = fixture_json("direct-flow/snapshot.json")["labels"][0]
    label["address"] = snapshot["transfers"][0]["destinationAccount"]
    snapshot["labels"] = [label]
    result = detector.evaluate(request)
    assert result["riskScore"] is None
    assert [r["ruleId"] for r in result["detectedRules"]] == ["SANCTION_DIRECT_FLOW"]
    assert label["address"] in result["evidences"][0]["relatedAddresses"]


def test_incident_label_is_not_sanctioned(detector, fixture_json):
    request = fixture_json("sanctioned/evaluation-request.json")
    request["snapshot"]["labels"][0]["type"] = "INCIDENT"
    assert detector.evaluate(request)["riskScore"] == 0


def test_zero_value_direct_flow_is_not_flagged(detector, fixture_json):
    request = fixture_json("direct-flow/evaluation-request.json")
    request["snapshot"]["transfers"][0]["amountRaw"] = "0"
    assert detector.evaluate(request)["detectedRules"] == []


@pytest.mark.parametrize("last_time,expected", [("2026-11-01T00:05:00Z", 35), ("2026-11-01T00:05:00.000001Z", 0)])
def test_fanout_time_boundary(detector, fixture_json, last_time, expected):
    request = fixture_json("warn/evaluation-request.json")
    request["snapshot"]["transfers"][-1]["timestamp"] = last_time
    assert detector.evaluate(request)["riskScore"] == expected


def test_multiple_instructions_in_one_transaction_do_not_count_as_repeats(detector, fixture_json, sync_snapshot):
    request = fixture_json("repeat/evaluation-request.json")
    rows = request["snapshot"]["transfers"]
    for index, row in enumerate(rows):
        row.update(signature=rows[0]["signature"], slot=rows[0]["slot"], timestamp=rows[0]["timestamp"], instructionIndex=index)
    assert detector.evaluate(sync_snapshot(request))["riskScore"] == 0


def test_repeats_are_grouped_by_asset(detector, fixture_json):
    request = fixture_json("repeat/evaluation-request.json")
    request["snapshot"]["transfers"][0]["asset"] = fixture_json("spl/snapshot.json")["transfers"][0]["asset"]
    assert detector.evaluate(request)["riskScore"] == 0


def test_rules_contribute_once_and_score_is_capped(detector, fixture_json):
    request = fixture_json("warn/evaluation-request.json")
    snapshot = request["snapshot"]
    label = fixture_json("direct-flow/snapshot.json")["labels"][0]
    label["address"] = snapshot["transfers"][0]["toAddress"]
    snapshot["labels"] = [label]
    result = detector.evaluate(request)
    assert result["riskScore"] == 100
    assert {r["ruleId"] for r in result["detectedRules"]} == {"SANCTION_DIRECT_FLOW", "RAPID_FAN_OUT"}


def test_deterministic_reordering_and_input_immutability(detector, fixture_json):
    request = fixture_json("warn/evaluation-request.json")
    original = deepcopy(request)
    result = detector.evaluate(request)
    assert request == original
    request["snapshot"]["transfers"].reverse()
    request["requestId"] = "another-correlation-id"
    assert detector.evaluate(request) == result
    result["evidences"][0]["source"]["dataProvenance"]["source"] = "changed"
    assert request["snapshot"]["dataProvenance"] == original["snapshot"]["dataProvenance"]


def test_huge_raw_amount_is_not_converted_to_float(detector, fixture_json):
    request = fixture_json("spl/evaluation-request.json")
    original_amount = request["snapshot"]["transfers"][0]["amountRaw"]
    label = fixture_json("direct-flow/snapshot.json")["labels"][0]
    label["address"] = request["snapshot"]["transfers"][0]["sourceAccount"]
    request["snapshot"]["labels"] = [label]
    assert detector.evaluate(request)["riskScore"] == 80
    assert request["snapshot"]["transfers"][0]["amountRaw"] == original_amount


def test_ruleset_version_selection_and_disabled_rule(fixture_json):
    config = read_json("config/rulesets/1.0.0.json")
    config["version"] = "1.2.0"
    config["rules"]["SANCTION_EXACT"]["enabled"] = False
    engine = Detector({"1.2.0": config})
    config["rules"]["SANCTION_EXACT"]["enabled"] = True
    request = fixture_json("sanctioned/evaluation-request.json")
    request["rulesetVersion"] = "1.2.0"
    assert engine.evaluate(request)["riskScore"] == 0
    request["rulesetVersion"] = "9.0.0"
    with pytest.raises(ContractViolation) as caught:
        engine.evaluate(request)
    assert caught.value.status == 422


def test_no_external_io_during_analysis(detector, fixture_json, monkeypatch):
    request = fixture_json("warn/evaluation-request.json")
    def forbidden(*args, **kwargs):
        raise AssertionError("External I/O attempted")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    assert detector.evaluate(request)["riskScore"] == 35


def test_sliding_window_matches_independent_brute_force(fixture_json):
    rng = random.Random(7021)
    template = fixture_json("warn/snapshot.json")["transfers"][0]
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    for _ in range(60):
        rows = []
        for i in range(rng.randrange(1, 35)):
            row = deepcopy(template)
            row.update(id=str(i), timestamp=(start + timedelta(seconds=rng.randrange(100))).isoformat().replace("+00:00", "Z"), toAddress=str(rng.randrange(6)))
            rows.append(row)
        ordered = sorted(rows, key=lambda r: r["timestamp"])
        expected = set()
        for left in range(len(ordered)):
            for right in range(left, len(ordered)):
                subset = ordered[left:right + 1]
                if datetime.fromisoformat(subset[-1]["timestamp"]) - datetime.fromisoformat(subset[0]["timestamp"]) <= timedelta(seconds=20) and len({r["toAddress"] for r in subset}) >= 3:
                    expected.update(r["id"] for r in subset)
        actual = _temporal_matches(rows, 20, 3, lambda row: row["toAddress"])
        assert {r["id"] for r in actual} == expected
