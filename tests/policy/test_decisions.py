from copy import deepcopy
import socket
import sqlite3

import pytest

from compliance_contracts.runtime import ContractViolation, ROOT, read_json, validate
from policy_engine import PolicyEngine

SCENARIOS = sorted(path.parent.name for path in (ROOT / "fixtures").glob("*/policy-request.json"))


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_contract_golden_outputs(policy, fixture_json, scenario):
    result = policy.decide(fixture_json(scenario + "/policy-request.json"))
    assert result == fixture_json(scenario + "/decision.json")
    validate("policy", "ComplianceDecision", result)


def test_versioned_direct_flow_action(policy, fixture_json):
    request = fixture_json("direct-flow/policy-request.json")
    assert policy.decide(request)["action"] == "REVIEW"
    request["policyVersion"] = "1.1.0"
    assert policy.decide(request) == fixture_json("direct-flow/block-decision.json")


def test_exact_match_wins_over_incomplete_data(policy, fixture_json):
    result = policy.decide(fixture_json("partial-sanctioned/policy-request.json"))
    assert result["action"] == "BLOCK" and result["riskScore"] is None
    assert set(result["reasonCodes"]) == {"SANCTION_EXACT_MATCH", "INSUFFICIENT_ASSESSMENT"}


def test_sender_risk_is_evaluated_not_only_recipient(policy, fixture_json):
    request = fixture_json("sanctioned/policy-request.json")
    request["intent"]["sender"], request["intent"]["recipient"] = request["intent"]["recipient"], request["intent"]["sender"]
    request["assessments"]["sender"], request["assessments"]["recipient"] = request["assessments"]["recipient"], request["assessments"]["sender"]
    assert policy.decide(request)["action"] == "BLOCK"


def test_missing_assessment_is_invalid_not_a_zero_score(policy, fixture_json):
    request = fixture_json("normal/policy-request.json")
    request["assessments"].pop("recipient")
    with pytest.raises(ContractViolation):
        policy.decide(request)


def test_unrelated_assessment_is_rejected(policy, fixture_json):
    request = fixture_json("normal/policy-request.json")
    request["assessments"]["recipient"] = deepcopy(request["assessments"]["sender"])
    with pytest.raises(ContractViolation):
        policy.decide(request)


@pytest.mark.parametrize("mutation", [
    lambda e: e["evidences"][0].update(labelReferenceIds=[]),
    lambda e: e["evidences"][0].update(type="TEMPORAL_PATTERN"),
    lambda e: e["detectedRules"][0].update(evidenceIds=["absent"]),
    lambda e: e.update(riskScore=1),
])
def test_inconsistent_assessments_are_rejected(policy, fixture_json, mutation):
    request = fixture_json("sanctioned/policy-request.json")
    mutation(request["assessments"]["recipient"])
    with pytest.raises(ContractViolation):
        policy.decide(request)


def test_same_address_uses_one_identical_assessment(policy, fixture_json):
    request = fixture_json("sanctioned/policy-request.json")
    request["intent"]["sender"] = request["intent"]["recipient"]
    request["assessments"]["sender"] = deepcopy(request["assessments"]["recipient"])
    result = policy.decide(request)
    assert result["riskScore"] == 100
    assert len(result["referencedEvidenceIds"]) == 1


def test_input_not_mutated_and_correlation_does_not_change_decision(policy, fixture_json):
    request = fixture_json("warn/policy-request.json")
    original = deepcopy(request)
    result = policy.decide(request)
    assert request == original
    request["requestId"] = "other-request"
    request["assessments"]["recipient"]["evidences"][0]["relatedAddresses"].reverse()
    request["assessments"]["recipient"]["evidences"][0]["transferIds"].reverse()
    assert policy.decide(request) == result


def test_policy_does_not_import_or_execute_detection(policy, fixture_json, monkeypatch):
    import kyt_engine
    def forbidden(*args, **kwargs):
        raise AssertionError("Forbidden dependency")
    monkeypatch.setattr(kyt_engine.Detector, "evaluate", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    assert policy.decide(fixture_json("warn/policy-request.json"))["action"] == "WARN"


@pytest.mark.parametrize("field", ["policyVersion", "rulesetVersion"])
def test_unknown_version_never_falls_back(policy, fixture_json, field):
    request = fixture_json("normal/policy-request.json")
    if field == "policyVersion":
        request[field] = "9.0.0"
    else:
        request["assessments"]["recipient"][field] = "9.0.0"
    with pytest.raises(ContractViolation) as caught:
        policy.decide(request)
    assert caught.value.status == 422


def test_custom_warning_policy_is_versioned_and_defensively_copied(fixture_json):
    config = read_json("config/policies/1.0.0.json")
    config.update(version="1.2.0", warningAction="REVIEW")
    policy = PolicyEngine({"1.2.0": config})
    config["warningAction"] = "WARN"
    request = fixture_json("warn/policy-request.json")
    request["policyVersion"] = "1.2.0"
    assert policy.decide(request)["action"] == "REVIEW"


def test_incomplete_sender_cannot_hide_exact_recipient(policy, fixture_json):
    request = fixture_json("sanctioned/policy-request.json")
    request["assessments"]["sender"].update(riskScore=None, riskLevel=None)
    result = policy.decide(request)
    assert result["action"] == "BLOCK"
    assert result["riskScore"] is None and result["riskLevel"] is None


def test_high_risk_policy_overrides_warning_action(fixture_json):
    from kyt_engine import Detector
    rules = read_json("config/rulesets/1.0.0.json")
    rules["version"] = "1.2.0"
    rules["rules"]["RAPID_FAN_OUT"].update(score=75, ruleVersion="1.2.0")
    query = fixture_json("warn/evaluation-request.json")
    query["rulesetVersion"] = "1.2.0"
    assessment = Detector({"1.2.0": rules}).evaluate(query)
    config = read_json("config/policies/1.0.0.json")
    config.update(version="1.2.0", supportedRulesetVersions=["1.0.0", "1.2.0"], highRiskAction="BLOCK")
    request = fixture_json("warn/policy-request.json")
    request.update(policyVersion="1.2.0")
    request["assessments"]["recipient"] = assessment
    result = PolicyEngine({"1.2.0": config}).decide(request)
    assert result["action"] == "BLOCK" and result["riskScore"] == 75 and result["riskLevel"] == "HIGH"
    assert set(result["reasonCodes"]) == {"HIGH_RISK_BLOCK", "RISK_SIGNALS_DETECTED"}
