"""Run from the repository root: python contracts/validate.py."""
from copy import deepcopy
from urllib.parse import urljoin
import yaml
from jsonschema import Draft202012Validator
from openapi_spec_validator import OpenAPIV31SpecValidator
from runtime import ROOT, ContractViolation, link_evaluation, read_json, registry, require, validate, walk

def main():
    schemas = sorted((ROOT / "schemas").glob("*.schema.json"))
    for path in schemas:
        data = read_json(path.relative_to(ROOT))
        Draft202012Validator.check_schema(data)
        for node in walk(data):
            if "$ref" in node:
                registry().resolver(data["$id"]).lookup(node["$ref"])
    spec = yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))
    spec_uri = (ROOT / "openapi.yaml").as_uri()
    OpenAPIV31SpecValidator(spec, base_uri=spec_uri).validate()
    operations = [op for item in spec["paths"].values() for op in item.values()]
    require(sum(op["x-audience"]=="PUBLIC" for op in operations)==6, "Expected six Public operations")
    require(sum(op["x-audience"]=="INTERNAL" for op in operations)==5, "Expected five Internal operations")
    for operation in operations:
        contents = list(operation.get("requestBody", {}).get("content", {}).values())
        for response in operation["responses"].values():
            contents.extend(response.get("content", {}).values())
        for media in contents:
            uri = urljoin(spec_uri, media["schema"]["$ref"])
            registry().resolver().lookup(uri)
            for example in media.get("examples", {}).values():
                file, name = media["schema"]["$ref"].split(".schema.json#/$defs/")
                validate(file.split("/")[-1], name, read_json(example["externalValue"]))
    manifest = read_json("fixtures/manifest.json")
    paths = set()
    for entry in manifest["fixtures"]:
        path = entry["path"]
        require(path not in paths, "Duplicate fixture manifest entry")
        paths.add(path)
        file, definition = entry["schema"].split(".schema.json#/$defs/")
        try:
            validate(file.split("/")[-1], definition, read_json("fixtures/" + path))
        except Exception as error:
            raise ValueError(f"Fixture failed: {path}: {error}") from error
    actual = {p.relative_to(ROOT / "fixtures").as_posix() for p in (ROOT / "fixtures").rglob("*.json") if p.name != "manifest.json"}
    require(paths == actual, "Every fixture must appear in manifest")
    validate("kyt", "Ruleset", read_json("config/rulesets/1.0.0.json"))
    for version in ["1.0.0", "1.1.0"]:
        validate("policy", "Policy", read_json(f"config/policies/{version}.json"))
    require(read_json("config/protocol-models.json")["approvedVersions"] == [], "Research-approved model is not supplied yet")
    for directory in sorted((ROOT / "fixtures").iterdir()):
        if not directory.is_dir() or not (directory / "snapshot.json").exists():
            continue
        prefix = directory.relative_to(ROOT).as_posix()
        snapshot, evaluation = read_json(prefix + "/snapshot.json"), read_json(prefix + "/evaluation.json")
        link_evaluation(snapshot, evaluation)
        collection = read_json(prefix + "/collection-request.json")
        require(all(collection[key] == snapshot[key] for key in ["requestId", "address", "network", "mode"]), "Collection/snapshot identity drift")
        require(collection["scope"]["fromTime"] == snapshot["coverage"]["fromTime"] and collection["scope"]["toTime"] == snapshot["coverage"]["toTime"], "Collection time scope drift")
        require(snapshot["coverage"]["transactionCount"] <= collection["scope"]["maxTransactions"], "Collection transaction cap violated")
        require(read_json(prefix + "/evaluation-request.json")["snapshot"] == snapshot, "Embedded snapshot drift")
        analysis = read_json(prefix + "/analysis.json")
        require(analysis["evaluation"] == evaluation and analysis["coverage"] == snapshot["coverage"], "Analysis drift")
        if (directory / "policy-request.json").exists():
            request, decision = read_json(prefix + "/policy-request.json"), read_json(prefix + "/decision.json")
            require(request["assessments"]["recipient"] == evaluation, "Embedded recipient assessment drift")
            require(request["assessments"]["sender"] == read_json("fixtures/sender/evaluation.json"), "Embedded sender assessment drift")
            require(request["intent"]["intentId"] == decision["intentId"], "Decision intent mismatch")
            require(request["policyVersion"] == decision["policyVersion"], "Decision policy mismatch")
            public = read_json(prefix + "/public-policy-response.json")
            require(public["decision"] == decision and public["assessments"] == request["assessments"], "Public response drift")
    matrix = {
        "allow": ("SUBMISSION_ALLOWED", "POLICY_ALLOW"), "block": ("SUBMISSION_REJECTED", "POLICY_BLOCK"),
        "review": ("REVIEW_REQUIRED", "POLICY_REVIEW"), "warning-unacknowledged": ("REVIEW_REQUIRED", "WARNING_NOT_ACKNOWLEDGED"),
        "warning-acknowledged": ("SUBMISSION_ALLOWED", "WARNING_ACKNOWLEDGED"), "alternative-path": ("SUBMISSION_ALLOWED", "POLICY_NOT_ENFORCED")
    }
    for name, (outcome, reason) in matrix.items():
        request = read_json(f"fixtures/gateway/{name}-request.json")
        result = read_json(f"fixtures/gateway/{name}-result.json")
        require(result["intentId"] == request["intent"]["intentId"] and result["routeId"] == request["route"]["routeId"], "Gateway linkage mismatch")
        require(result["policyApplied"] == request["route"]["policyEnforced"], "Gateway policy flag mismatch")
        require(result["outcome"] == outcome and result["reasonCodes"] == [reason], "Gateway expectation drift")
    negative_count = 0
    def reject(path, file, definition, mutation):
        nonlocal negative_count
        data = deepcopy(read_json(path))
        mutation(data)
        try:
            validate(file, definition, data)
        except ContractViolation:
            negative_count += 1
            return
        raise ValueError(f"Invalid contract accepted: {path}, case {negative_count+1}")
    for value in [1, None, "-1", "1.5", "1e9", "01"]:
        reject("fixtures/normal/snapshot.json", "collector", "KYTDataSnapshot", lambda d,v=value: d["transfers"][0].update(amountRaw=v))
    for mutation in [
        lambda d: d.pop("address"), lambda d: d.update(unexpected=True), lambda d: d.update(mode="live"),
        lambda d: d.pop("fixtureId"), lambda d: d.update(mode="LIVE"),
        lambda d: d["scope"].update(toTime="2026-11-02T09:00:00+09:00"),
        lambda d: d["scope"].update(toTime="2026-02-30T00:00:00Z"),
        lambda d: d["scope"].update(toTime="2026-10-01T00:00:00Z")
    ]:
        reject("fixtures/normal/collection-request.json", "collector", "KYTCollectionRequest", mutation)
    for mutation in [
        lambda d: d.update(schemaVersion="0.2.0"), lambda d: d.update(address="1"*44),
        lambda d: d["transfers"].append(deepcopy(d["transfers"][0])),
        lambda d: d["coverage"].update(transferCount=999),
        lambda d: d["transfers"][0].update(ownerResolved=False),
        lambda d: d["coverage"].update(status="PARTIAL"),
        lambda d: d["transfers"][0]["asset"].update(mint=d["address"])
    ]:
        reject("fixtures/normal/snapshot.json","collector","KYTDataSnapshot",mutation)
    reject("fixtures/partial/evaluation.json","kyt","KYTEvaluation",lambda d:d.update(riskScore=0))
    reject("fixtures/warn/evaluation.json","kyt","KYTEvaluation",lambda d:d.update(riskLevel="LOW",riskScore=0))
    reject("fixtures/warn/evaluation.json","kyt","KYTEvaluation",lambda d:d["detectedRules"][0].update(evidenceIds=["missing"]))
    reject("fixtures/normal/policy-request.json","policy","PolicyDecisionRequest",lambda d:d["intent"].update(amountRaw="0"))
    reject("fixtures/normal/policy-request.json","policy","PolicyDecisionRequest",lambda d:d["intent"].update(recipient=d["intent"]["sender"]))
    reject("fixtures/gateway/block-request.json","experiment","GatewayExperimentRequest",lambda d:d["decision"].update(intentId="other"))
    reject("fixtures/gateway/block-result.json","experiment","GatewayExperimentResult",lambda d:d.update(actualBroadcast=True))
    reject("fixtures/constellation/mock-result.json","experiment","ConstellationSimulationResult",lambda d:d.update(simulationOnly=False))
    reject("fixtures/api/failed.json","api","KYTAnalysisResult",lambda d:d.update(error=None))
    reject("fixtures/normal/analysis.json","api","KYTAnalysisResult",lambda d:d.update(status="PARTIAL"))
    for path in [ROOT/"README.md",ROOT/"semantics.md",ROOT/"openapi.yaml",*schemas,*(ROOT/"fixtures").rglob("*.json")]:
        content = path.read_text(encoding="utf-8")
        require("\ufffd" not in content and "??" not in content, "Damaged UTF-8 text")
    print(f"PASS: {len(schemas)} schemas, {len(operations)} operations, {len(paths)} fixtures, {negative_count} rejected inputs, linked scenarios")

if __name__ == "__main__":
    main()
