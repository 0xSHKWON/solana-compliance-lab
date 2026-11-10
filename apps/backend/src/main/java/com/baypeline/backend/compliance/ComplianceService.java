package com.baypeline.backend.compliance;

import com.baypeline.backend.analysis.AnalysisJob;
import com.baypeline.backend.analysis.AnalysisService;
import com.baypeline.backend.support.ApiContracts;
import com.baypeline.backend.support.ApiException;
import com.baypeline.backend.support.Contract;
import com.baypeline.backend.support.PolicyContracts;
import com.baypeline.backend.upstream.UpstreamException;
import com.baypeline.backend.upstream.UpstreamServices;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.time.Clock;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

/**
 * POST /api/v1/compliance/evaluate. 저장된 분석 결과로 Internal PolicyDecisionRequest를 구성해
 * Policy Engine에 전달하고, intent·assessments·decision을 함께 저장·반환한다. 정책 판단은 하지 않는다.
 */
@Service
public class ComplianceService {

    private static final JsonNodeFactory JSON = JsonNodeFactory.instance;

    private final AnalysisService analyses;
    private final UpstreamServices upstream;
    private final ReviewRepository reviews;
    private final Clock clock;

    public ComplianceService(AnalysisService analyses, UpstreamServices upstream, ReviewRepository reviews,
            Clock clock) {
        this.analyses = analyses;
        this.upstream = upstream;
        this.reviews = reviews;
        this.clock = clock;
    }

    public ObjectNode evaluate(JsonNode request, String requestId) {
        ApiContracts.complianceRequest(request);
        JsonNode intent = request.get("intent");
        String senderId = request.get("senderAnalysisId").textValue();
        String recipientId = request.get("recipientAnalysisId").textValue();
        String policyVersion = request.get("policyVersion").textValue();

        AnalysisJob sender = ready(analyses.find(senderId), "sender");
        AnalysisJob recipient = ready(analyses.find(recipientId), "recipient");
        String senderAddress = intent.get("sender").textValue();
        String recipientAddress = intent.get("recipient").textValue();
        if (!sender.address().equals(senderAddress)) {
            throw mismatch("senderAnalysisId does not belong to intent.sender");
        }
        if (!recipient.address().equals(recipientAddress)) {
            throw mismatch("recipientAnalysisId does not belong to intent.recipient");
        }
        if (senderAddress.equals(recipientAddress) && !senderId.equals(recipientId)) {
            throw mismatch("sender and recipient are the same address; use the same analysis");
        }

        ObjectNode assessments = JSON.objectNode();
        assessments.set("sender", sender.evaluation());
        assessments.set("recipient", recipient.evaluation());

        ObjectNode policyRequest = JSON.objectNode();
        policyRequest.put("requestId", requestId);
        policyRequest.set("intent", intent);
        policyRequest.set("assessments", assessments);
        policyRequest.put("policyVersion", policyVersion);

        JsonNode decision;
        try {
            decision = upstream.decidePolicy(requestId, policyRequest);
        } catch (UpstreamException e) {
            throw e.toPublic();
        }
        checkDecision(decision, intent, policyVersion);

        reviews.save(new ReviewRecord(decision.get("decisionId").textValue(), intent.get("intentId").textValue(),
                requestId, senderId, recipientId, intent, assessments, decision, clock.instant()));

        ObjectNode response = JSON.objectNode();
        response.put("schemaVersion", Contract.SCHEMA_VERSION);
        response.put("requestId", requestId);
        response.set("intent", intent);
        response.set("assessments", assessments);
        response.set("decision", decision);
        return response;
    }

    private static AnalysisJob ready(AnalysisJob job, String role) {
        if (!job.status().hasResult()) {
            throw new ApiException(HttpStatus.CONFLICT, "ANALYSIS_NOT_READY",
                    role + " analysis is " + job.status(), job.status() != AnalysisJob.JobStatus.FAILED);
        }
        return job;
    }

    private static ApiException mismatch(String message) {
        return new ApiException(HttpStatus.CONFLICT, "ASSESSMENT_MISMATCH", message, false);
    }

    private static void checkDecision(JsonNode decision, JsonNode intent, String policyVersion) {
        try {
            PolicyContracts.decision(decision, "decision");
        } catch (ApiException e) {
            throw UpstreamException.invalidResponse("policy-engine", e.getMessage()).toPublic();
        }
        if (!intent.get("intentId").textValue().equals(decision.get("intentId").textValue())) {
            throw UpstreamException.invalidResponse("policy-engine", "intentId mismatch").toPublic();
        }
        if (!policyVersion.equals(decision.get("policyVersion").textValue())) {
            throw UpstreamException.invalidResponse("policy-engine", "policyVersion mismatch").toPublic();
        }
    }
}
