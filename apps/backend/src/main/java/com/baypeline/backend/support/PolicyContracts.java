package com.baypeline.backend.support;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
import java.util.Set;

/** policy.schema.json 의 TransactionIntent·Asset·ComplianceDecision 구조 검증. */
public final class PolicyContracts {

    public static final Set<String> ACTIONS = Set.of("ALLOW", "WARN", "REVIEW", "BLOCK");
    public static final Set<String> RISK_LEVELS = Set.of("LOW", "MEDIUM", "HIGH");
    public static final Set<String> REASON_CODES = Set.of("NO_RISK_SIGNALS", "SANCTION_EXACT_MATCH",
            "SANCTION_DIRECT_FLOW_REVIEW", "SANCTION_DIRECT_FLOW_BLOCK", "INSUFFICIENT_ASSESSMENT",
            "RISK_SIGNALS_DETECTED", "HIGH_RISK_REVIEW", "HIGH_RISK_BLOCK", "HIGH_RISK_WARN");
    private static final Set<String> ASSET_TYPES = Set.of("SOL", "SPL", "TOKEN_2022");

    private PolicyContracts() {
    }

    public static void intent(JsonNode node, String path) {
        Contract.object(node, path,
                List.of("intentId", "network", "sender", "recipient", "asset", "amountRaw", "requestedAt"), List.of());
        Contract.id(node.get("intentId"), path + ".intentId");
        Contract.constant(node.get("network"), path + ".network", "mainnet-beta");
        Contract.address(node.get("sender"), path + ".sender");
        Contract.address(node.get("recipient"), path + ".recipient");
        asset(node.get("asset"), path + ".asset");
        Contract.positiveRawAmount(node.get("amountRaw"), path + ".amountRaw");
        Contract.timestamp(node.get("requestedAt"), path + ".requestedAt");
    }

    public static void asset(JsonNode node, String path) {
        Contract.object(node, path, List.of("type", "mint", "decimals"), List.of());
        String type = Contract.enumValue(node.get("type"), path + ".type", ASSET_TYPES);
        long decimals = Contract.integer(node.get("decimals"), path + ".decimals", 0, 255);
        if ("SOL".equals(type)) {
            if (!Contract.isNull(node.get("mint"))) {
                throw ApiException.contract(path + ".mint must be null for SOL");
            }
            if (decimals != 9) {
                throw ApiException.contract(path + ".decimals must be 9 for SOL");
            }
        } else {
            Contract.address(node.get("mint"), path + ".mint");
        }
    }

    /** 지원하지 않는 schemaVersion은 다른 스키마 오류보다 먼저 422로 거부한다. */
    public static void schemaVersionFirst(JsonNode node) {
        if (node != null && node.isObject() && node.has("schemaVersion")) {
            JsonNode version = node.get("schemaVersion");
            if (!version.isTextual() || !Contract.SCHEMA_VERSION.equals(version.textValue())) {
                throw ApiException.unsupportedVersion("Unsupported schemaVersion");
            }
        }
    }

    public static void decision(JsonNode node, String path) {
        Contract.object(node, path, List.of("schemaVersion", "decisionId", "intentId", "action", "riskScore",
                "riskLevel", "reasonCodes", "referencedEvidenceIds", "policyVersion", "evaluatedAt"), List.of());
        Contract.constant(node.get("schemaVersion"), path + ".schemaVersion", Contract.SCHEMA_VERSION);
        Contract.id(node.get("decisionId"), path + ".decisionId");
        Contract.id(node.get("intentId"), path + ".intentId");
        Contract.enumValue(node.get("action"), path + ".action", ACTIONS);
        riskPair(node, path);
        Contract.uniqueStrings(node.get("reasonCodes"), path + ".reasonCodes", 1, REASON_CODES);
        Contract.uniqueStrings(node.get("referencedEvidenceIds"), path + ".referencedEvidenceIds", 0, null);
        Contract.version(node.get("policyVersion"), path + ".policyVersion");
        Contract.timestamp(node.get("evaluatedAt"), path + ".evaluatedAt");
    }

    /** riskScore null ↔ riskLevel null, 0 → LOW, 양수 → MEDIUM/HIGH. */
    private static void riskPair(JsonNode node, String path) {
        JsonNode score = node.get("riskScore");
        JsonNode level = node.get("riskLevel");
        if (Contract.isNull(score)) {
            if (!Contract.isNull(level)) {
                throw ApiException.contract(path + ".riskLevel must be null when riskScore is null");
            }
            return;
        }
        long value = Contract.integer(score, path + ".riskScore", 0, 100);
        String riskLevel = Contract.enumValue(level, path + ".riskLevel", RISK_LEVELS);
        if (value == 0 && !"LOW".equals(riskLevel)) {
            throw ApiException.contract(path + ".riskLevel must be LOW when riskScore is 0");
        }
        if (value > 0 && "LOW".equals(riskLevel)) {
            throw ApiException.contract(path + ".riskLevel must be MEDIUM or HIGH when riskScore is positive");
        }
    }
}
