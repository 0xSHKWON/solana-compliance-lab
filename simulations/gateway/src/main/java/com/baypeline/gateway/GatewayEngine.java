package com.baypeline.gateway;

import com.baypeline.gateway.support.ApiException;
import com.baypeline.gateway.support.Contract;
import com.baypeline.gateway.support.PolicyContracts;
import com.baypeline.gateway.support.StableIds;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.List;
import org.springframework.stereotype.Component;

/**
 * GatewayExperimentRequest → GatewayExperimentResult.
 *
 * <p>정책 결정을 다시 판단하지 않고, 제출 경로(route)의 정책 적용 여부에 따라
 * 결정의 action을 어떻게 집행하는지만 재현한다. 실제 네트워크 송신은 하지 않는다.
 *
 * <pre>
 * policyEnforced | action | warningAcknowledged | outcome             | reasonCodes
 * false          | *      | *                   | SUBMISSION_ALLOWED  | POLICY_NOT_ENFORCED
 * true           | ALLOW  | *                   | SUBMISSION_ALLOWED  | POLICY_ALLOW
 * true           | BLOCK  | *                   | SUBMISSION_REJECTED | POLICY_BLOCK
 * true           | REVIEW | *                   | REVIEW_REQUIRED     | POLICY_REVIEW
 * true           | WARN   | false               | REVIEW_REQUIRED     | WARNING_NOT_ACKNOWLEDGED
 * true           | WARN   | true                | SUBMISSION_ALLOWED  | WARNING_ACKNOWLEDGED
 * </pre>
 */
@Component
public class GatewayEngine {

    private static final JsonNodeFactory JSON = JsonNodeFactory.instance;

    public ObjectNode experiment(JsonNode request) {
        validate(request);
        JsonNode intent = request.get("intent");
        JsonNode decision = request.get("decision");
        JsonNode route = request.get("route");

        String intentId = intent.get("intentId").textValue();
        if (!intentId.equals(decision.get("intentId").textValue())) {
            throw ApiException.invalid("intent.intentId and decision.intentId must match");
        }

        boolean enforced = route.get("policyEnforced").booleanValue();
        boolean acknowledged = route.get("warningAcknowledged").booleanValue();
        String action = decision.get("action").textValue();

        Verdict verdict = judge(enforced, action, acknowledged);

        ObjectNode identity = JSON.objectNode();
        identity.put("intentId", intentId);
        identity.put("decisionId", decision.get("decisionId").textValue());
        identity.set("route", route.deepCopy());

        ObjectNode result = JSON.objectNode();
        result.put("schemaVersion", Contract.SCHEMA_VERSION);
        result.put("experimentId", StableIds.of("experiment", identity));
        result.put("intentId", intentId);
        result.put("routeId", route.get("routeId").textValue());
        result.put("outcome", verdict.outcome());
        result.put("policyApplied", enforced);
        result.set("reasonCodes", JSON.arrayNode().add(verdict.reason()));
        result.put("actualBroadcast", false);
        return result;
    }

    static Verdict judge(boolean policyEnforced, String action, boolean warningAcknowledged) {
        if (!policyEnforced) {
            return new Verdict("SUBMISSION_ALLOWED", "POLICY_NOT_ENFORCED");
        }
        return switch (action) {
            case "ALLOW" -> new Verdict("SUBMISSION_ALLOWED", "POLICY_ALLOW");
            case "BLOCK" -> new Verdict("SUBMISSION_REJECTED", "POLICY_BLOCK");
            case "REVIEW" -> new Verdict("REVIEW_REQUIRED", "POLICY_REVIEW");
            case "WARN" -> warningAcknowledged
                    ? new Verdict("SUBMISSION_ALLOWED", "WARNING_ACKNOWLEDGED")
                    : new Verdict("REVIEW_REQUIRED", "WARNING_NOT_ACKNOWLEDGED");
            default -> throw ApiException.contract("decision.action is not supported");
        };
    }

    private static void validate(JsonNode request) {
        if (request != null && request.isObject()) {
            PolicyContracts.schemaVersionFirst(request.get("decision"));
        }
        Contract.object(request, "request", List.of("requestId", "intent", "decision", "route"), List.of());
        Contract.id(request.get("requestId"), "request.requestId");
        PolicyContracts.intent(request.get("intent"), "request.intent");
        PolicyContracts.decision(request.get("decision"), "request.decision");
        JsonNode route = request.get("route");
        Contract.object(route, "request.route", List.of("routeId", "policyEnforced", "warningAcknowledged"),
                List.of());
        Contract.id(route.get("routeId"), "request.route.routeId");
        Contract.bool(route.get("policyEnforced"), "request.route.policyEnforced");
        Contract.bool(route.get("warningAcknowledged"), "request.route.warningAcknowledged");
    }

    record Verdict(String outcome, String reason) {
    }
}
