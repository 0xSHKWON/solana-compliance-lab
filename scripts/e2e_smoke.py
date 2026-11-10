"""Backend Public API E2E 스모크 테스트.

실제 KYT/Policy 엔진 + Gateway/Constellation + Backend(로컬 fixture Collector)를 띄운 상태에서
Public API 전체 흐름을 호출하고, 모든 응답을 solana-compliance-lab/contracts 의 JSON Schema로 검증한다.

    scripts/run-local.sh start
    .venv/bin/python scripts/e2e_smoke.py
"""
import json, os, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from contracts.runtime import validate

BASE = os.environ.get("BACKEND_URL", "http://127.0.0.1:8080")
SENDER = "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"
RECIPIENT = "8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR"
results = []

def call(method, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), json.loads(e.read())

def check(name, cond, detail=""):
    results.append((name, cond))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {detail}"))

def schema(name, file, definition, value):
    try:
        validate(file, definition, value); check(name + " schema", True)
    except Exception as e:
        check(name + " schema", False, e)

def analyze(address, fixture, ruleset=None):
    body = {"address": address, "network": "mainnet-beta", "mode": "FIXTURE", "fixtureId": fixture,
            "scope": {"fromTime": "2026-11-01T00:00:00Z", "toTime": "2026-11-02T00:00:00Z", "maxTransactions": 100}}
    if ruleset: body["rulesetVersion"] = ruleset
    s, h, b = call("POST", "/api/v1/analyses", body)
    check(f"analyze {fixture} 202", s == 202, (s, b))
    schema(f"accepted {fixture}", "api", "AnalysisAccepted", b)
    check(f"analyze {fixture} Location", h.get("Location") == f"/api/v1/analyses/{b['analysisId']}", h)
    for _ in range(50):
        s, _, r = call("GET", f"/api/v1/analyses/{b['analysisId']}")
        if r["status"] in ("COMPLETED", "PARTIAL", "FAILED"): break
        time.sleep(0.1)
    schema(f"analysis {fixture} {r['status']}", "api", "KYTAnalysisResult", r)
    return r

intent = lambda iid: {"intentId": iid, "network": "mainnet-beta", "sender": SENDER, "recipient": RECIPIENT,
                      "asset": {"type": "SOL", "mint": None, "decimals": 9}, "amountRaw": "1000000000", "requestedAt": "2026-11-02T00:00:00Z"}

def comply(iid, sender, recipient, version="1.0.0"):
    s, _, b = call("POST", "/api/v1/compliance/evaluate", {"intent": intent(iid), "senderAnalysisId": sender["analysisId"],
                   "recipientAnalysisId": recipient["analysisId"], "policyVersion": version})
    check(f"compliance {iid} 200", s == 200, (s, b))
    if s == 200: schema(f"compliance {iid}", "api", "ComplianceResponse", b)
    return b

def gateway(iid, decision, route_id, enforced, ack):
    s, _, b = call("POST", "/api/v1/experiments/gateway", {"intentId": iid, "decisionId": decision["decisionId"],
                   "route": {"routeId": route_id, "policyEnforced": enforced, "warningAcknowledged": ack}})
    check(f"gateway {route_id} 200", s == 200, (s, b))
    if s == 200: schema(f"gateway {route_id}", "experiment", "GatewayExperimentResult", b)
    return b

# 1) analyses
sender = analyze(SENDER, "sender")
check("sender COMPLETED LOW", sender["status"] == "COMPLETED" and sender["evaluation"]["riskLevel"] == "LOW", sender["status"])
sanctioned = analyze(RECIPIENT, "sanctioned")
check("sanctioned HIGH 100", sanctioned["evaluation"]["riskScore"] == 100, sanctioned.get("evaluation"))
partial = analyze(RECIPIENT, "partial")
check("partial PARTIAL null score", partial["status"] == "PARTIAL" and partial["evaluation"]["riskScore"] is None, partial["status"])
warn = analyze(RECIPIENT, "warn")
direct = analyze(RECIPIENT, "direct-flow")
bad_ruleset = analyze(RECIPIENT, "normal", ruleset="9.9.9")
check("unsupported ruleset FAILED/UNSUPPORTED_VERSION", bad_ruleset["status"] == "FAILED" and bad_ruleset["error"]["code"] == "UNSUPPORTED_VERSION", bad_ruleset.get("error"))
wrong_addr = analyze(SENDER, "sanctioned")
check("fixture/address mismatch FAILED", wrong_addr["status"] == "FAILED", wrong_addr["status"])

# 2) transfers
s, _, page = call("GET", f"/api/v1/analyses/{warn['analysisId']}/transfers?limit=2")
check("transfers 200", s == 200, page); schema("transfers p1", "api", "TransferPage", page)
check("transfers p1 has cursor", len(page["items"]) == 2 and page["pagination"]["nextCursor"], page["pagination"])
s, _, page2 = call("GET", f"/api/v1/analyses/{warn['analysisId']}/transfers?limit=2&cursor={page['pagination']['nextCursor']}")
schema("transfers p2", "api", "TransferPage", page2)
check("transfers p2 last page", len(page2["items"]) == 1 and page2["pagination"]["nextCursor"] is None, page2["pagination"])
s, _, e = call("GET", f"/api/v1/analyses/{bad_ruleset['analysisId']}/transfers")
check("transfers FAILED -> 409", s == 409 and e["error"]["code"] == "ANALYSIS_NOT_READY", (s, e)); schema("409 error", "common", "ErrorResponse", e)

# 3) compliance + gateway decision table
block = comply("sanctioned-intent", sender, sanctioned)
check("sanctioned -> BLOCK", block["decision"]["action"] == "BLOCK", block["decision"]["action"])
r = gateway("sanctioned-intent", block["decision"], "block", True, False)
check("enforced BLOCK -> REJECTED", r["outcome"] == "SUBMISSION_REJECTED" and r["reasonCodes"] == ["POLICY_BLOCK"], r)
r = gateway("sanctioned-intent", block["decision"], "bypass", False, False)
check("not enforced -> ALLOWED (bypass comparison)", r["outcome"] == "SUBMISSION_ALLOWED" and r["reasonCodes"] == ["POLICY_NOT_ENFORCED"] and r["actualBroadcast"] is False, r)

w = comply("warn-intent", sender, warn)
check("warn -> WARN", w["decision"]["action"] == "WARN", w["decision"]["action"])
r = gateway("warn-intent", w["decision"], "warn-unack", True, False)
check("WARN unack -> REVIEW_REQUIRED", r["outcome"] == "REVIEW_REQUIRED" and r["reasonCodes"] == ["WARNING_NOT_ACKNOWLEDGED"], r)
r = gateway("warn-intent", w["decision"], "warn-ack", True, True)
check("WARN ack -> ALLOWED", r["outcome"] == "SUBMISSION_ALLOWED" and r["reasonCodes"] == ["WARNING_ACKNOWLEDGED"], r)

p = comply("partial-intent", sender, partial)
check("partial -> REVIEW", p["decision"]["action"] == "REVIEW", p["decision"])
r = gateway("partial-intent", p["decision"], "review", True, False)
check("REVIEW -> REVIEW_REQUIRED", r["outcome"] == "REVIEW_REQUIRED", r)

ok = comply("normal-intent", sender, analyze(RECIPIENT, "normal"))
check("normal -> ALLOW", ok["decision"]["action"] == "ALLOW", ok["decision"]["action"])
r = gateway("normal-intent", ok["decision"], "allow", True, False)
check("ALLOW -> ALLOWED", r["outcome"] == "SUBMISSION_ALLOWED" and r["reasonCodes"] == ["POLICY_ALLOW"], r)

d10 = comply("direct-intent", sender, direct, "1.0.0"); d11 = comply("direct-intent", sender, direct, "1.1.0")
check("direct-flow policy 1.0.0 REVIEW / 1.1.0 BLOCK", d10["decision"]["action"] == "REVIEW" and d11["decision"]["action"] == "BLOCK",
      (d10["decision"]["action"], d11["decision"]["action"]))

s, _, e = call("POST", "/api/v1/compliance/evaluate", {"intent": intent("x"), "senderAnalysisId": sanctioned["analysisId"],
               "recipientAnalysisId": sender["analysisId"], "policyVersion": "1.0.0"})
check("swapped analyses -> 409 ASSESSMENT_MISMATCH", s == 409 and e["error"]["code"] == "ASSESSMENT_MISMATCH", (s, e))
s, _, e = call("POST", "/api/v1/compliance/evaluate", {"intent": intent("x"), "senderAnalysisId": sender["analysisId"],
               "recipientAnalysisId": sanctioned["analysisId"], "policyVersion": "7.0.0"})
check("unknown policyVersion -> 422", s == 422 and e["error"]["code"] == "UNSUPPORTED_VERSION", (s, e))

# 4) constellation
scenario = {"proposerCount": 4, "rejectingProposerCount": 1, "submittedToAcceptingProposer": True, "psliceAvailable": True,
            "attestationPercent": 100, "leaderAttemptsExclusion": True}
s, _, c = call("POST", "/api/v1/experiments/constellation", {"intentId": "sanctioned-intent", "decisionId": block["decision"]["decisionId"],
               "protocolModelVersion": "0.0.0-research-pending", "scenario": scenario})
check("constellation mock 200", s == 200, (s, c)); schema("constellation", "experiment", "ConstellationSimulationResult", c)
s, _, c = call("POST", "/api/v1/experiments/constellation", {"intentId": "sanctioned-intent", "decisionId": block["decision"]["decisionId"],
               "protocolModelVersion": "0.0.0-research-pending", "scenario": {**scenario, "rejectingProposerCount": 9}})
check("constellation INVALID_SCENARIO", s == 200 and c["outcome"] == "INVALID_SCENARIO", c); schema("constellation invalid", "experiment", "ConstellationSimulationResult", c)
s, _, c = call("POST", "/api/v1/experiments/constellation", {"intentId": "sanctioned-intent", "decisionId": block["decision"]["decisionId"],
               "protocolModelVersion": "1.0.0", "scenario": scenario})
check("constellation unapproved -> 422", s == 422 and c["error"]["code"] == "UNSUPPORTED_VERSION", (s, c))

# 4b) constellation draft vs single-leader baseline (same scenario)
def simulate(version, sc):
    s, _, c = call("POST", "/api/v1/experiments/constellation", {"intentId": "sanctioned-intent", "decisionId": block["decision"]["decisionId"],
                   "protocolModelVersion": version, "scenario": sc})
    check(f"constellation {version} 200", s == 200, (s, c))
    if s == 200: schema(f"constellation {version}", "experiment", "ConstellationSimulationResult", c)
    return c
c = simulate("0.1.0-draft", scenario)
check("draft: attested pslice -> INCLUSION_ENFORCED, exclusion invalid", c["outcome"] == "INCLUSION_ENFORCED" and c["leaderExclusionValid"] is False, c)
c = simulate("0.1.0-single-leader", scenario)
check("baseline: INCLUSION_NOT_ENFORCED, exclusion valid", c["outcome"] == "INCLUSION_NOT_ENFORCED" and c["leaderExclusionValid"] is True, c)
c = simulate("0.1.0-draft", {**scenario, "attestationPercent": 50})
check("draft: low attestation -> NOT_ENFORCED", c["outcome"] == "INCLUSION_NOT_ENFORCED" and "ATTESTATION_CONDITION_NOT_MET" in c["explanationCodes"], c)
c = simulate("0.1.0-draft", {**scenario, "rejectingProposerCount": 4, "submittedToAcceptingProposer": False})
check("draft: all reject -> NO_SUBMISSION_PATH", c["outcome"] == "NO_SUBMISSION_PATH" and c["explanationCodes"] == ["NO_ACCEPTING_PROPOSER"], c)

# 5) errors / headers
s, h, e = call("GET", "/api/v1/analyses/missing", headers={"X-Request-ID": "trace-e2e"})
check("404 + X-Request-ID echo", s == 404 and e["requestId"] == "trace-e2e" and h.get("X-Request-ID") == "trace-e2e", (s, e, h.get("X-Request-ID")))
schema("404 error", "common", "ErrorResponse", e)

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
