"""Deterministic, side-effect-free analysis of normalized snapshots."""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import timedelta

from compliance_contracts.runtime import (
    ContractViolation, instant, link_evaluation, read_json, require, stable_id, validate,
)


def _order(transfer):
    return (instant(transfer["timestamp"]), transfer["signature"], transfer["instructionIndex"],
            -1 if transfer["innerInstructionIndex"] is None else transfer["innerInstructionIndex"],
            transfer["transferOrdinal"], transfer["id"])


def _temporal_matches(transfers, seconds, minimum, key):
    """Union of qualifying time windows in O(n log n) time, O(n) space.

    A merged interval representation avoids repeatedly copying large windows.
    """
    rows = sorted(transfers, key=_order)
    counts, left, intervals = Counter(), 0, []
    window = timedelta(seconds=seconds)
    for right, row in enumerate(rows):
        counts[key(row)] += 1
        while instant(row["timestamp"]) - instant(rows[left]["timestamp"]) > window:
            previous = key(rows[left])
            counts[previous] -= 1
            if not counts[previous]:
                del counts[previous]
            left += 1
        if len(counts) >= minimum:
            if intervals and left <= intervals[-1][1] + 1:
                intervals[-1][1] = right
            else:
                intervals.append([left, right])
    return [rows[i] for start, stop in intervals for i in range(start, stop + 1)]


def _evidence(snapshot, rule_id, transfers, labels):
    addresses = {snapshot["address"]}
    for row in transfers:
        addresses.update(row[key] for key in ["fromAddress", "toAddress", "sourceAccount", "destinationAccount"] if row[key] is not None)
    addresses.update(label["address"] for label in labels)
    evidence = {
        "type": {"SANCTION_EXACT": "ADDRESS_LABEL", "SANCTION_DIRECT_FLOW": "DIRECT_FLOW"}.get(rule_id, "TEMPORAL_PATTERN"),
        "transactionSignatures": sorted({row["signature"] for row in transfers}),
        "transferIds": sorted(row["id"] for row in transfers),
        "relatedAddresses": sorted(addresses),
        "labelReferenceIds": sorted({label["referenceId"] for label in labels}),
        "source": {"snapshotId": snapshot["snapshotId"], "network": snapshot["network"], "mode": snapshot["mode"],
                   "dataProvenance": deepcopy(snapshot["dataProvenance"]), "labelDataset": deepcopy(snapshot["labelDataset"])},
    }
    return {"evidenceId": stable_id("evidence", {"ruleId": rule_id, **evidence}), **evidence}


class Detector:
    def __init__(self, rulesets=None):
        self._rulesets = deepcopy(rulesets if rulesets is not None else {"1.0.0": read_json("config/rulesets/1.0.0.json")})
        for version, config in self._rulesets.items():
            validate("kyt", "Ruleset", config)
            require(version == config["version"], "Ruleset registry version mismatch")

    def evaluate(self, request):
        validate("kyt", "KYTEvaluationRequest", request)
        version, snapshot = request["rulesetVersion"], request["snapshot"]
        if version not in self._rulesets:
            raise ContractViolation("Unsupported rulesetVersion", "UNSUPPORTED_VERSION", 422)
        config = self._rulesets[version]
        subject = snapshot["address"]
        labels = [label for label in snapshot["labels"] if label["type"] == "SANCTIONED"]
        label_index = defaultdict(list)
        for label in labels:
            label_index[label["address"]].append(label)
        exact = label_index[subject]
        matches = {}
        if exact:
            matches["SANCTION_EXACT"] = ([], exact)
        direct, direct_labels = {}, {}
        for row in snapshot["transfers"]:
            if row["amountRaw"] == "0":
                continue
            counterpart = set()
            if row["fromAddress"] == subject:
                counterpart.update([row["toAddress"], row["destinationAccount"]])
            if row["toAddress"] == subject:
                counterpart.update([row["fromAddress"], row["sourceAccount"]])
            counterpart.discard(subject)
            hits = [label for address in counterpart for label in label_index.get(address, [])]
            if hits:
                direct[row["id"]] = row
                for label in hits:
                    direct_labels[(label["address"], label["source"], label["referenceId"])] = label
        if direct:
            matches["SANCTION_DIRECT_FLOW"] = (list(direct.values()), list(direct_labels.values()))
        outgoing = [row for row in snapshot["transfers"] if row["fromAddress"] == subject
                    and row["ownerResolved"] and row["timestamp"] is not None and row["amountRaw"] != "0"
                    and row["toAddress"] != subject]
        fan = config["rules"]["RAPID_FAN_OUT"]
        fan_rows = _temporal_matches(outgoing, fan["windowSeconds"], fan["minRecipients"], lambda row: row["toAddress"])
        if fan_rows:
            matches["RAPID_FAN_OUT"] = (fan_rows, [])
        groups = defaultdict(list)
        for row in outgoing:
            groups[(row["toAddress"], row["asset"]["type"], row["asset"]["mint"])].append(row)
        repeat, repeated_rows = config["rules"]["RAPID_REPEAT"], []
        for group in groups.values():
            repeated_rows.extend(_temporal_matches(group, repeat["windowSeconds"], repeat["minTransactions"], lambda row: row["signature"]))
        if repeated_rows:
            matches["RAPID_REPEAT"] = (repeated_rows, [])
        detected, evidences = [], []
        for rule_id in sorted(matches):
            rule = config["rules"][rule_id]
            if not rule["enabled"]:
                continue
            evidence = _evidence(snapshot, rule_id, *matches[rule_id])
            evidences.append(evidence)
            detected.append({"ruleId": rule_id, "ruleVersion": rule["ruleVersion"], "riskLevel": rule["riskLevel"],
                             "scoreContribution": rule["score"], "evidenceIds": [evidence["evidenceId"]]})
        score = None if snapshot["coverage"]["status"] == "PARTIAL" else min(100, sum(rule["scoreContribution"] for rule in detected))
        level = None if score is None else ("LOW" if score == 0 else ("HIGH" if score >= config["highRiskThreshold"] else "MEDIUM"))
        result = {"schemaVersion": "0.1.0", "subjectAddress": subject, "snapshotId": snapshot["snapshotId"],
                  "rulesetVersion": version, "riskScore": score, "riskLevel": level,
                  "detectedRules": detected, "evidences": sorted(evidences, key=lambda item: item["evidenceId"])}
        validate("kyt", "KYTEvaluation", result)
        link_evaluation(snapshot, result)
        return result
