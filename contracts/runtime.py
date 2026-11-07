"""Local schema and semantic validation shared by contract tests and engines."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent
VERSION = "0.1.0"
BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


class ContractViolation(ValueError):
    def __init__(self, message, code="CONTRACT_VALIDATION_FAILED", status=400):
        super().__init__(message)
        self.code, self.status = code, status


def require(condition, message):
    if not condition:
        raise ContractViolation(message, "INVALID_REQUEST")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(prefix, value):
    return prefix + "-" + hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def unique(values, description):
    values = list(values)
    require(len(values) == len(set(values)), "Duplicate " + description)


def base58_size(value):
    number = 0
    for char in value:
        number = number * 58 + BASE58.index(char)
    return len(value) - len(value.lstrip("1")) + (number.bit_length() + 7) // 8


@lru_cache(maxsize=1)
def registry():
    result = Registry()
    for path in sorted((ROOT / "schemas").glob("*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(data)
        result = result.with_resource(data["$id"], resource).with_resource(path.as_uri(), resource)
    return result


@lru_cache(maxsize=64)
def validator(file, definition):
    uri = (ROOT / "schemas" / f"{file}.schema.json").as_uri() + "#/$defs/" + definition
    return Draft202012Validator({"$ref": uri}, registry=registry(), format_checker=FormatChecker())


def validate(file, definition, value):
    for node in walk(value):
        if "schemaVersion" in node and node["schemaVersion"] != VERSION:
            raise ContractViolation("Unsupported schemaVersion", "UNSUPPORTED_VERSION", 422)
    error = next(validator(file, definition).iter_errors(value), None)
    if error is not None:
        location = "/" + "/".join(map(str, error.absolute_path))
        raise ContractViolation(f"Schema violation at {location}: {error.validator}")
    semantic_checks(value)


def semantic_checks(value):
    for node in walk(value):
        for key, address in node.items():
            if key in {"address", "subjectAddress", "sender", "recipient", "fromAddress", "toAddress", "sourceAccount", "destinationAccount", "mint"} and isinstance(address, str):
                require(base58_size(address) == 32, f"Invalid decoded address: {key}")
            if key == "signature":
                require(base58_size(address) == 64, "Invalid decoded signature")
        for address in node.get("relatedAddresses", []):
            require(base58_size(address) == 32, "Invalid related address")
        for signature in node.get("transactionSignatures", []):
            require(base58_size(signature) == 64, "Invalid evidence signature")
        if {"fromTime", "toTime"} <= node.keys():
            require(instant(node["fromTime"]) < instant(node["toTime"]), "Empty or inverted time range")
        if {"snapshotId", "coverage", "transfers", "labels"} <= node.keys():
            snapshot_checks(node)
        if {"subjectAddress", "detectedRules", "evidences", "riskScore"} <= node.keys():
            evaluation_checks(node)
        if {"intent", "assessments", "policyVersion"} <= node.keys():
            request_checks(node)
        if {"intent", "decision"} <= node.keys():
            require(node["intent"]["intentId"] == node["decision"]["intentId"], "Decision intent mismatch")
        if {"analysisId", "evaluation", "snapshotId", "status"} <= node.keys() and node["evaluation"] is not None:
            require(node["address"] == node["evaluation"]["subjectAddress"], "Analysis address mismatch")
            require(node["snapshotId"] == node["evaluation"]["snapshotId"], "Analysis snapshot mismatch")


def snapshot_checks(snapshot):
    transfers, coverage = snapshot["transfers"], snapshot["coverage"]
    unique((t["id"] for t in transfers), "transfer ID")
    unique(((t["signature"], t["instructionIndex"], t["innerInstructionIndex"], t["transferOrdinal"]) for t in transfers), "transfer position")
    unique(((l["address"], l["source"], l["referenceId"]) for l in snapshot["labels"]), "address label")
    require(coverage["transferCount"] == len(transfers), "Transfer count mismatch")
    require(coverage["transactionCount"] >= len({t["signature"] for t in transfers}), "Transaction count too small")
    transactions, decimals = {}, {}
    for transfer in transfers:
        require(transfer["ownerResolved"] == (transfer["fromAddress"] is not None and transfer["toAddress"] is not None), "Owner resolution flag mismatch")
        if not transfer["ownerResolved"]:
            require("OWNER_UNRESOLVED" in coverage["reasons"], "Unresolved owner not reported")
        if transfer["timestamp"] is None:
            require("TIMESTAMP_UNAVAILABLE" in coverage["reasons"], "Missing timestamp not reported")
        else:
            require(instant(coverage["fromTime"]) <= instant(transfer["timestamp"]) < instant(coverage["toTime"]), "Transfer outside collected range")
        if coverage["snapshotSlot"] is not None:
            require(transfer["slot"] <= coverage["snapshotSlot"], "Transfer beyond snapshot slot")
        tx_meta = (transfer["slot"], transfer["timestamp"])
        require(transfer["signature"] not in transactions or transactions[transfer["signature"]] == tx_meta, "Inconsistent transaction metadata")
        transactions[transfer["signature"]] = tx_meta
        asset = transfer["asset"]
        asset_key = (asset["type"], asset["mint"])
        require(asset_key not in decimals or decimals[asset_key] == asset["decimals"], "Inconsistent asset decimals")
        decimals[asset_key] = asset["decimals"]
        if asset["type"] == "SOL":
            require(transfer["sourceAccount"] == transfer["fromAddress"] and transfer["destinationAccount"] == transfer["toAddress"], "SOL accounts must be wallet addresses")
    for label in snapshot["labels"]:
        require(label["network"] == snapshot["network"], "Label network mismatch")
        require(label["source"] == snapshot["labelDataset"]["source"], "Label dataset mismatch")


def evaluation_checks(evaluation):
    rules, evidences = evaluation["detectedRules"], evaluation["evidences"]
    unique((r["ruleId"] for r in rules), "detected rule")
    unique((e["evidenceId"] for e in evidences), "evidence ID")
    ids = {e["evidenceId"] for e in evidences}
    used = {eid for r in rules for eid in r["evidenceIds"]}
    require(ids == used, "Missing or orphan evidence")
    for evidence in evidences:
        require(evidence["source"]["snapshotId"] == evaluation["snapshotId"], "Evidence snapshot mismatch")
    if evaluation["riskScore"] is not None:
        require(evaluation["riskScore"] == min(100, sum(r["scoreContribution"] for r in rules)), "Score contribution mismatch")


def request_checks(request):
    intent, assessments = request["intent"], request["assessments"]
    for party in ["sender", "recipient"]:
        require(assessments[party]["subjectAddress"] == intent[party], f"{party} assessment address mismatch")
    if intent["sender"] == intent["recipient"]:
        require(assessments["sender"] == assessments["recipient"], "Conflicting same-address assessments")
    seen = {}
    for assessment in assessments.values():
        for evidence in assessment["evidences"]:
            eid = evidence["evidenceId"]
            require(eid not in seen or seen[eid] == evidence, "Conflicting evidence ID")
            seen[eid] = evidence


def link_evaluation(snapshot, evaluation):
    require(evaluation["subjectAddress"] == snapshot["address"], "Evaluation address mismatch")
    require(evaluation["snapshotId"] == snapshot["snapshotId"], "Evaluation snapshot mismatch")
    require((evaluation["riskScore"] is None) == (snapshot["coverage"]["status"] == "PARTIAL"), "Completeness/score mismatch")
    transfers = {t["id"]: t for t in snapshot["transfers"]}
    labels = {label["referenceId"] for label in snapshot["labels"]}
    source = {"snapshotId": snapshot["snapshotId"], "network": snapshot["network"], "mode": snapshot["mode"],
              "dataProvenance": snapshot["dataProvenance"], "labelDataset": snapshot["labelDataset"]}
    for evidence in evaluation["evidences"]:
        require(evidence["source"] == source, "Evidence source mismatch")
        require(set(evidence["transferIds"]) <= transfers.keys(), "Dangling transfer reference")
        require(set(evidence["labelReferenceIds"]) <= labels, "Dangling label reference")
        signatures = {transfers[tid]["signature"] for tid in evidence["transferIds"]}
        require(set(evidence["transactionSignatures"]) == signatures, "Evidence signature mismatch")
