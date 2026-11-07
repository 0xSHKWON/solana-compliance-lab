"""Validate local draft contracts without fetching repository schemas over HTTP."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import yaml
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from openapi_spec_validator import OpenAPIV31SpecValidator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parent
FORMAT = FormatChecker()
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def unique(items, key):
    values = [item[key] for item in items]
    require(len(set(values)) == len(values), f"Duplicate {key}")


def decoded_size(value):
    number = 0
    for character in value:
        number = number * 58 + ALPHABET.index(character)
    leading = len(value) - len(value.lstrip("1"))
    return leading + (number.bit_length() + 7) // 8


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def semantic_checks(name, data):
    """Portable invariants that ordinary JSON Schema cannot express.

    This is a contract checker, not an implementation of the detection engines.
    Cross-resource and service-level requirements remain in semantics.md.
    """
    for node in walk(data):
        if "from" in node and "to" in node:
            require(instant(node["from"]) <= instant(node["to"]), "Inverted time range")
        for key, value in node.items():
            if key in {"walletAddress", "address", "sender", "recipient", "mint"} and value is not None:
                require(decoded_size(value) == 32, f"Invalid decoded address: {key}")
            if key == "signature" and value is not None:
                require(decoded_size(value) == 64, "Invalid decoded signature")
        for key in ["timeRange", "requestedRange"]:
            if key in node:
                span = node[key]
                require(instant(span["from"]) < instant(span["to"]), "Empty requested range")
        if {"ruleSetId", "thresholds", "rules"} <= node.keys():
            unique(node["rules"], "ruleId")
            t = node["thresholds"]
            require(1 <= t["medium"] < t["high"] < t["critical"] <= 100, "Invalid score thresholds")
        if {"fetchedTransactionCount", "normalizedTransactionCount"} <= node.keys():
            require(0 <= node["normalizedTransactionCount"] <= node["fetchedTransactionCount"] <= node["maxTransactions"], "Invalid transaction counts")
        for array_key, item_key in [
            ("transfers", "transferId"), ("labels", "labelId"), ("findings", "findingId"),
            ("routes", "routeId"), ("proposers", "proposerId"),
        ]:
            if array_key in node:
                unique(node[array_key], item_key)
        if {"riskLevel", "unevaluatedRuleIds"} <= node.keys():
            require((node["riskLevel"] == "UNKNOWN") == bool(node["unevaluatedRuleIds"]), "UNKNOWN must correspond to unevaluated rules")

    if name == "KYTDataSnapshot":
        times = [t["blockTime"] for t in data["transfers"] if t["blockTime"] is not None]
        observed = data["coverage"]["observedRange"]
        require(bool(times) == (observed is not None), "Observed range must match known transfer times")
        if times:
            require(instant(observed["from"]) == min(map(instant, times)) and instant(observed["to"]) == max(map(instant, times)), "Observed range must cover transfer timestamps")
        if any(t["blockTime"] is None for t in data["transfers"]):
            require(any(i["code"] == "MISSING_BLOCK_TIME" for i in data["coverage"]["issues"]), "Missing block time must be reported")
    if name == "DecisionRequest":
        unique(data["evaluations"], "walletAddress")
        parties = {data["transferRequest"]["sender"], data["transferRequest"]["recipient"]}
        versions = {(e["ruleSetId"], e["ruleSetVersion"]) for e in data["evaluations"]}
        require(len(versions) <= 1, "Mixed rule versions")
        require(all(e["walletAddress"] in parties for e in data["evaluations"]), "Unrelated wallet evaluation")
        require(all(instant(e["evaluatedAt"]) <= instant(data["asOf"]) for e in data["evaluations"]), "Future evaluation")
    if name == "GatewayRequest":
        require(data["transferRequest"]["transferRequestId"] == data["complianceDecision"]["transferRequestId"], "Decision does not match transfer")
    if name == "SimulationRequest":
        require(not data["proof"]["conditionSatisfied"] or any(p["acceptsTransaction"] for p in data["proposers"]), "Proof without an accepting proposer")


def link_evaluation(snapshot, evaluation, rule_set):
    require(evaluation["snapshotId"] == snapshot["snapshotId"], "Snapshot ID mismatch")
    require(evaluation["walletAddress"] == snapshot["walletAddress"], "Wallet mismatch")
    require(evaluation["coverageStatus"] == snapshot["coverage"]["status"], "Coverage mismatch")
    require((evaluation["ruleSetId"], evaluation["ruleSetVersion"]) == (rule_set["ruleSetId"], rule_set["version"]), "Rule version mismatch")
    rules = {r["ruleId"]: r for r in rule_set["rules"]}
    transfers = {t["transferId"] for t in snapshot["transfers"]}
    labels = {label["labelId"] for label in snapshot["labels"]}
    for finding in evaluation["findings"]:
        rule_id = finding["ruleId"]
        require(rule_id in rules and rules[rule_id]["enabled"], "Unknown or disabled finding rule")
        require(rule_id not in evaluation["unevaluatedRuleIds"], "Finding from unevaluated rule")
        evidence = finding["evidence"]
        require(evidence["snapshotId"] == snapshot["snapshotId"], "Evidence snapshot mismatch")
        require(set(evidence["transferIds"]) <= transfers, "Dangling transfer evidence")
        require(set(evidence["labelIds"]) <= labels, "Dangling label evidence")
    require(set(evaluation["unevaluatedRuleIds"]) <= rules.keys(), "Unknown unevaluated rule")


def check_pipelines():
    expected = {"normal": (0, "LOW", "ALLOW"), "sanctioned": (100, "CRITICAL", "BLOCK"),
                "partial": (None, "UNKNOWN", "REVIEW"), "warn": (40, "MEDIUM", "WARN")}
    sender = read("fixtures/sender/evaluation.json")
    link_evaluation(read("fixtures/sender/snapshot.json"), sender, read("config/demo-rules.json"))
    for scenario, (score, level, action) in expected.items():
        def fixture(name):
            return read(f"fixtures/{scenario}/{name}.json")
        request, evaluation = fixture("evaluation-request"), fixture("evaluation")
        require(request["snapshot"] == fixture("snapshot"), "Embedded snapshot drift")
        require(request["ruleSet"] == read("config/demo-rules.json"), "Embedded rules drift")
        link_evaluation(request["snapshot"], evaluation, request["ruleSet"])
        require((evaluation["riskScore"], evaluation["riskLevel"]) == (score, level), "Unexpected scenario risk")
        policy_request, decision = fixture("policy-request"), fixture("decision")
        require(policy_request["evaluations"] == [sender, evaluation], "Embedded evaluation drift")
        require(policy_request["policy"] == read("config/demo-policy.json"), "Embedded policy drift")
        require(decision["decision"] == action, "Unexpected scenario decision")
        require(decision["evaluationIds"] == [sender["evaluationId"], evaluation["evaluationId"]], "Decision references drift")
        require(decision["decidedAt"] == policy_request["asOf"], "Decision timestamp drift")
        require(decision["transferRequestId"] == policy_request["transferRequest"]["transferRequestId"], "Transfer reference drift")
        analysis = fixture("analysis")
        require(analysis["snapshot"] == request["snapshot"] and analysis["evaluation"] == evaluation, "Analysis result drift")
        public = fixture("public-policy-request")
        require(public["analysisIds"] == ["sender-analysis", analysis["analysisId"]], "Public analysis references drift")
        require(public["transferRequest"] == policy_request["transferRequest"], "Public transfer drift")
        gateway_request, gateway = fixture("gateway-request"), fixture("gateway-result")
        require(gateway_request["complianceDecision"] == decision, "Gateway decision drift")
        require(gateway_request["transferRequest"] == policy_request["transferRequest"], "Gateway transfer drift")
        require(gateway["decisionId"] == decision["decisionId"], "Gateway result reference drift")
        require(gateway["transferRequestId"] == decision["transferRequestId"], "Gateway transfer result drift")
        expected_outcome = {"ALLOW": "SUBMITTED", "BLOCK": "REJECTED", "REVIEW": "HELD_FOR_REVIEW", "WARN": "AWAITING_CONFIRMATION"}[action]
        require(gateway["routes"][0]["outcome"] == expected_outcome, "Gateway scenario outcome drift")
        require(gateway["routes"][1]["outcome"] == "SUBMITTED", "Alternative path fixture drift")
    confirmed = read("fixtures/warn/confirmed-gateway-result.json")
    require(confirmed["routes"][0]["outcome"] == "SUBMITTED", "Confirmed warning fixture drift")
    for case, forced, count in [("proof-satisfied", True, 1), ("proof-missing", False, 1), ("all-reject", False, 0)]:
        request = read(f"fixtures/constellation/{case}-request.json")
        result = read(f"fixtures/constellation/{case}-result.json")
        require(result["simulationId"] == request["simulationId"], "Simulation ID drift")
        require(result["acceptingProposerCount"] == count, "Simulation count drift")
        require(result["rejectingProposerCount"] == len(request["proposers"]) - count, "Rejecting count drift")
        require(result["proofConditionSatisfied"] == request["proof"]["conditionSatisfied"], "Proof input drift")
        require(result["inclusionForced"] == forced and result["leaderCanExclude"] != forced, "Simulation fixture outcome drift")


def main():
    schema_files = sorted((ROOT / "schemas").glob("*.schema.json"))
    text_files = [ROOT / "README.md", ROOT / "semantics.md", ROOT / "openapi.yaml", *schema_files,
                  *(ROOT / "fixtures").rglob("*.json"), *(ROOT / "config").glob("*.json")]
    for path in text_files:
        raw = path.read_text(encoding="utf-8")
        require("\ufffd" not in raw and "??" not in raw, f"Damaged text encoding: {path}")
    registry = Registry()
    documents = []
    for path in schema_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(data)
        resource = Resource.from_contents(data)
        registry = registry.with_resource(path.as_uri(), resource).with_resource(data["$id"], resource)
        documents.append((data["$id"], data))
    spec = yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))
    spec_uri = (ROOT / "openapi.yaml").as_uri()
    registry = registry.with_resource(spec_uri, Resource.from_contents(spec, default_specification=DRAFT202012))
    documents.append((spec_uri, spec))
    for uri, document in documents:
        for node in walk(document):
            if "$ref" in node:
                registry.resolver(uri).lookup(node["$ref"])
    OpenAPIV31SpecValidator(spec, base_uri=spec_uri).validate()

    def validate(schema_uri, data):
        Draft202012Validator({"$ref": schema_uri}, registry=registry, format_checker=FORMAT).validate(data)
        semantic_checks(schema_uri.rsplit("/", 1)[-1], data)

    manifest = read("fixtures/manifest.json")
    listed = set()
    for entry in manifest["fixtures"]:
        path = entry["path"]
        require(path not in listed, f"Duplicate manifest entry: {path}")
        listed.add(path)
        uri = urljoin((ROOT / "fixtures" / "manifest.json").as_uri(), entry["schema"])
        try:
            validate(uri, read("fixtures/" + path))
        except Exception as error:
            raise ValueError(f"Fixture failed: {path}: {error}") from error
    actual = {p.relative_to(ROOT / "fixtures").as_posix() for p in (ROOT / "fixtures").rglob("*.json") if p.name != "manifest.json"}
    require(listed == actual, "Manifest must cover every fixture")
    for name, file, definition in [("demo-rules", "kyt", "RuleSet"), ("demo-policy", "policy", "PolicyConfig")]:
        validate((ROOT / f"schemas/{file}.schema.json").as_uri() + "#/$defs/" + definition, read(f"config/{name}.json"))
    for path_item in spec["paths"].values():
        for operation in path_item.values():
            media = []
            if "requestBody" in operation:
                media.extend(operation["requestBody"]["content"].values())
            for response in operation["responses"].values():
                media.extend(response.get("content", {}).values())
            for item in media:
                for example in item.get("examples", {}).values():
                    validate(urljoin(spec_uri, item["schema"]["$ref"]), read(example["externalValue"]))

    # Boundary regressions: each mutation must fail, even if another valid fixture exists.
    negative_count = 0

    def reject(path, file, definition, mutate):
        nonlocal negative_count
        data = deepcopy(read(path))
        mutate(data)
        uri = (ROOT / f"schemas/{file}.schema.json").as_uri() + "#/$defs/" + definition
        try:
            validate(uri, data)
        except (ValueError, ValidationError):
            negative_count += 1
            return
        raise ValueError(f"Invalid input accepted: {path}, case {negative_count + 1}")

    for amount in [1, None, "-1", "1.5", "1e6", "01"]:
        reject("fixtures/normal/snapshot.json", "collector", "KYTDataSnapshot", lambda d, value=amount: d["transfers"][0].update(amountRaw=value))
    for mutate in [lambda d: d.pop("walletAddress"), lambda d: d.update(unexpected=True), lambda d: d.update(mode="live"),
                   lambda d: d.update(schemaVersion="2.0.0"), lambda d: d.pop("fixtureId"),
                   lambda d: d.update(mode="LIVE"),
                   lambda d: d["timeRange"].update(to="2026-11-02T09:00:00+09:00"),
                   lambda d: d["timeRange"].update(to="2026-02-30T00:00:00Z"),
                   lambda d: d["timeRange"].update(to="2026-10-01T00:00:00Z")]:
        reject("fixtures/normal/collection-request.json", "collector", "CollectionRequest", mutate)
    reject("fixtures/normal/snapshot.json", "collector", "KYTDataSnapshot", lambda d: d.update(walletAddress="1" * 44))
    reject("fixtures/normal/snapshot.json", "collector", "KYTDataSnapshot", lambda d: d["transfers"].append(deepcopy(d["transfers"][0])))
    reject("fixtures/normal/snapshot.json", "collector", "KYTDataSnapshot", lambda d: d["coverage"].update(status="PARTIAL"))
    reject("fixtures/normal/snapshot.json", "collector", "KYTDataSnapshot", lambda d: d["coverage"].update(normalizedTransactionCount=2))
    reject("fixtures/partial/evaluation.json", "kyt", "KYTEvaluation", lambda d: d.update(riskScore=0))
    reject("fixtures/normal/evaluation.json", "kyt", "KYTEvaluation", lambda d: d.update(unevaluatedRuleIds=["sanction-address"]))
    reject("config/demo-rules.json", "kyt", "RuleSet", lambda d: d["thresholds"].update(medium=80))
    reject("config/demo-rules.json", "kyt", "RuleSet", lambda d: d.update(version="0.1.0-01"))
    reject("fixtures/normal/policy-request.json", "policy", "DecisionRequest", lambda d: d["transferRequest"].update(amountRaw="0"))
    reject("fixtures/normal/policy-request.json", "policy", "DecisionRequest", lambda d: d["evaluations"].__setitem__(1, deepcopy(d["evaluations"][0])))
    reject("fixtures/normal/gateway-request.json", "experiment", "GatewayRequest", lambda d: d["complianceDecision"].update(transferRequestId="other-transfer"))
    reject("fixtures/normal/gateway-result.json", "experiment", "GatewayExperimentResult", lambda d: d.update(networkSubmitted=True))
    reject("fixtures/api/failed.json", "api", "KYTAnalysisResult", lambda d: d.update(error=None))
    reject("fixtures/api/running.json", "api", "KYTAnalysisResult", lambda d: d.update(snapshot=read("fixtures/normal/snapshot.json")))
    reject("fixtures/normal/analysis.json", "api", "KYTAnalysisResult", lambda d: d.update(status="PARTIAL"))
    reject("fixtures/constellation/all-reject-request.json", "experiment", "SimulationRequest", lambda d: d["proof"].update(conditionSatisfied=True))
    check_pipelines()
    print(f"PASS: {len(schema_files)} schemas, OpenAPI 3.1, {len(listed)} fixtures, 2 configs, {negative_count} negative cases, linked scenario expectations")


if __name__ == "__main__":
    main()
