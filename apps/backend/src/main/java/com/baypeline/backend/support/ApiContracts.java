package com.baypeline.backend.support;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.Instant;
import java.util.List;
import java.util.Set;

/** api.schema.json 의 Public 요청 구조 검증. */
public final class ApiContracts {

    private static final Set<String> MODES = Set.of("LIVE", "FIXTURE");

    private ApiContracts() {
    }

    public static void analysisRequest(JsonNode node) {
        Contract.object(node, "request", List.of("address", "network", "mode", "scope"),
                List.of("fixtureId", "rulesetVersion"));
        Contract.address(node.get("address"), "request.address");
        Contract.constant(node.get("network"), "request.network", "mainnet-beta");
        String mode = Contract.enumValue(node.get("mode"), "request.mode", MODES);
        if ("FIXTURE".equals(mode)) {
            if (!node.has("fixtureId")) {
                throw ApiException.contract("request.fixtureId is required for FIXTURE mode");
            }
            Contract.id(node.get("fixtureId"), "request.fixtureId");
        } else if (node.has("fixtureId")) {
            throw ApiException.contract("request.fixtureId is not allowed for LIVE mode");
        }
        scope(node.get("scope"), "request.scope");
        if (node.has("rulesetVersion")) {
            Contract.version(node.get("rulesetVersion"), "request.rulesetVersion");
        }
    }

    /** 조회 구간은 [fromTime, toTime) 이며 fromTime < toTime. */
    public static void scope(JsonNode node, String path) {
        Contract.object(node, path, List.of("fromTime", "toTime", "maxTransactions"), List.of());
        String from = Contract.timestamp(node.get("fromTime"), path + ".fromTime");
        String to = Contract.timestamp(node.get("toTime"), path + ".toTime");
        Contract.integer(node.get("maxTransactions"), path + ".maxTransactions", 1, Long.MAX_VALUE);
        if (!Instant.parse(from).isBefore(Instant.parse(to))) {
            throw ApiException.invalid(path + ".fromTime must be before toTime");
        }
    }

    public static void complianceRequest(JsonNode node) {
        Contract.object(node, "request", List.of("intent", "senderAnalysisId", "recipientAnalysisId",
                "policyVersion"), List.of());
        PolicyContracts.intent(node.get("intent"), "request.intent");
        Contract.id(node.get("senderAnalysisId"), "request.senderAnalysisId");
        Contract.id(node.get("recipientAnalysisId"), "request.recipientAnalysisId");
        Contract.version(node.get("policyVersion"), "request.policyVersion");
    }

    public static void gatewayRequest(JsonNode node) {
        Contract.object(node, "request", List.of("intentId", "decisionId", "route"), List.of());
        Contract.id(node.get("intentId"), "request.intentId");
        Contract.id(node.get("decisionId"), "request.decisionId");
        JsonNode route = node.get("route");
        Contract.object(route, "request.route", List.of("routeId", "policyEnforced", "warningAcknowledged"),
                List.of());
        Contract.id(route.get("routeId"), "request.route.routeId");
        Contract.bool(route.get("policyEnforced"), "request.route.policyEnforced");
        Contract.bool(route.get("warningAcknowledged"), "request.route.warningAcknowledged");
    }

    public static void constellationRequest(JsonNode node) {
        Contract.object(node, "request", List.of("intentId", "decisionId", "protocolModelVersion", "scenario"),
                List.of());
        Contract.id(node.get("intentId"), "request.intentId");
        Contract.id(node.get("decisionId"), "request.decisionId");
        Contract.version(node.get("protocolModelVersion"), "request.protocolModelVersion");
        JsonNode scenario = node.get("scenario");
        String path = "request.scenario";
        Contract.object(scenario, path, List.of("proposerCount", "rejectingProposerCount",
                "submittedToAcceptingProposer", "psliceAvailable", "attestationPercent", "leaderAttemptsExclusion"),
                List.of());
        Contract.integer(scenario.get("proposerCount"), path + ".proposerCount", 1, Integer.MAX_VALUE);
        Contract.integer(scenario.get("rejectingProposerCount"), path + ".rejectingProposerCount", 0,
                Integer.MAX_VALUE);
        Contract.bool(scenario.get("submittedToAcceptingProposer"), path + ".submittedToAcceptingProposer");
        Contract.bool(scenario.get("psliceAvailable"), path + ".psliceAvailable");
        Contract.number(scenario.get("attestationPercent"), path + ".attestationPercent", 0, 100);
        Contract.bool(scenario.get("leaderAttemptsExclusion"), path + ".leaderAttemptsExclusion");
    }
}
