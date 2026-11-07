"""Versioned policy evaluation, independent of the KYT implementation."""
from copy import deepcopy

from compliance_contracts.runtime import ContractViolation, read_json, require, stable_id, validate

PRIORITY = {"ALLOW": 0, "WARN": 1, "REVIEW": 2, "BLOCK": 3}
LEVEL = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def _normalized_assessments(assessments):
    result = deepcopy(assessments)
    for evaluation in result.values():
        evaluation["detectedRules"].sort(key=lambda item: item["ruleId"])
        for rule in evaluation["detectedRules"]:
            rule["evidenceIds"].sort()
        evaluation["evidences"].sort(key=lambda item: item["evidenceId"])
        for evidence in evaluation["evidences"]:
            for field in ["transactionSignatures", "transferIds", "relatedAddresses", "labelReferenceIds"]:
                evidence[field].sort()
    return result


class PolicyEngine:
    def __init__(self, policies=None):
        self._policies = deepcopy(policies if policies is not None else {
            version: read_json(f"config/policies/{version}.json") for version in ["1.0.0", "1.1.0"]
        })
        for version, config in self._policies.items():
            validate("policy", "Policy", config)
            require(version == config["version"], "Policy registry version mismatch")

    def decide(self, request):
        validate("policy", "PolicyDecisionRequest", request)
        version = request["policyVersion"]
        if version not in self._policies:
            raise ContractViolation("Unsupported policyVersion", "UNSUPPORTED_VERSION", 422)
        config = self._policies[version]
        assessments = _normalized_assessments(request["assessments"])
        candidates, reasons, evidence_ids = ["ALLOW"], set(), set()
        for evaluation in assessments.values():
            if evaluation["rulesetVersion"] not in config["supportedRulesetVersions"]:
                raise ContractViolation("Unsupported assessment rulesetVersion", "UNSUPPORTED_VERSION", 422)
            rules = {rule["ruleId"] for rule in evaluation["detectedRules"]}
            evidence_ids.update(item["evidenceId"] for item in evaluation["evidences"])
            if evaluation["riskScore"] is None:
                candidates.append("REVIEW")
                reasons.add("INSUFFICIENT_ASSESSMENT")
            if "SANCTION_EXACT" in rules:
                candidates.append("BLOCK")
                reasons.add("SANCTION_EXACT_MATCH")
            elif "SANCTION_DIRECT_FLOW" in rules:
                candidates.append(config["directFlowAction"])
                reasons.add("SANCTION_DIRECT_FLOW_" + config["directFlowAction"])
            elif rules:
                candidates.append(config["warningAction"])
                reasons.add("RISK_SIGNALS_DETECTED")
                if evaluation["riskLevel"] == "HIGH":
                    candidates.append(config["highRiskAction"])
                    reasons.add("HIGH_RISK_" + config["highRiskAction"])
        values = list(assessments.values())
        score = None if any(value["riskScore"] is None for value in values) else max(value["riskScore"] for value in values)
        level = None if score is None else max((value["riskLevel"] for value in values), key=LEVEL.__getitem__)
        if not reasons:
            reasons.add("NO_RISK_SIGNALS")
        identity = {"intent": request["intent"], "assessments": assessments, "policyVersion": version}
        result = {"schemaVersion": "0.1.0", "decisionId": stable_id("decision", identity), "intentId": request["intent"]["intentId"],
                  "action": max(candidates, key=PRIORITY.__getitem__), "riskScore": score, "riskLevel": level,
                  "reasonCodes": sorted(reasons), "referencedEvidenceIds": sorted(evidence_ids),
                  "policyVersion": version, "evaluatedAt": request["intent"]["requestedAt"]}
        validate("policy", "ComplianceDecision", result)
        return result
