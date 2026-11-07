"""Run the actual offline KYT -> Policy pipeline using shared synthetic inputs."""
import argparse
import json

from compliance_contracts.runtime import read_json, validate
from kyt_engine import Detector
from policy_engine import PolicyEngine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="sanctioned", choices=[
        "normal", "empty", "sanctioned", "direct-flow", "warn", "repeat", "partial", "partial-sanctioned", "unresolved", "missing-time", "spl", "token-2022",
    ])
    parser.add_argument("--policy-version", default="1.0.0", choices=["1.0.0", "1.1.0"])
    args = parser.parse_args()
    detector = Detector()
    sender = detector.evaluate(read_json("fixtures/sender/evaluation-request.json"))
    recipient = detector.evaluate(read_json(f"fixtures/{args.scenario}/evaluation-request.json"))
    request = read_json(f"fixtures/{args.scenario}/policy-request.json")
    request["assessments"] = {"sender": sender, "recipient": recipient}
    request["policyVersion"] = args.policy_version
    decision = PolicyEngine().decide(request)
    gateway = {"requestId": "demo-gateway-request", "intent": request["intent"], "decision": decision,
               "route": {"routeId": "our-service", "policyEnforced": True, "warningAcknowledged": False}}
    validate("experiment", "GatewayExperimentRequest", gateway)
    print(json.dumps({"evaluation": recipient, "decision": decision, "gatewayRequest": gateway}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
