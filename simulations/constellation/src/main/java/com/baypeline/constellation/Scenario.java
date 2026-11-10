package com.baypeline.constellation;

import com.baypeline.constellation.support.Contract;
import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.util.List;

/** experiment.schema.json#/$defs/ConstellationScenario. */
public record Scenario(
        int proposerCount,
        int rejectingProposerCount,
        boolean submittedToAcceptingProposer,
        boolean psliceAvailable,
        BigDecimal attestationPercent,
        boolean leaderAttemptsExclusion) {

    static final List<String> FIELDS = List.of("proposerCount", "rejectingProposerCount",
            "submittedToAcceptingProposer", "psliceAvailable", "attestationPercent", "leaderAttemptsExclusion");

    public static Scenario parse(JsonNode node, String path) {
        Contract.object(node, path, FIELDS, List.of());
        return new Scenario(
                (int) Contract.integer(node.get("proposerCount"), path + ".proposerCount", 1, Integer.MAX_VALUE),
                (int) Contract.integer(node.get("rejectingProposerCount"), path + ".rejectingProposerCount", 0,
                        Integer.MAX_VALUE),
                Contract.bool(node.get("submittedToAcceptingProposer"), path + ".submittedToAcceptingProposer"),
                Contract.bool(node.get("psliceAvailable"), path + ".psliceAvailable"),
                attestation(node.get("attestationPercent"), path + ".attestationPercent"),
                Contract.bool(node.get("leaderAttemptsExclusion"), path + ".leaderAttemptsExclusion"));
    }

    /** 0~100 숫자. 부동소수점 오차 없이 임계값과 비교하도록 BigDecimal로 보관한다. */
    private static BigDecimal attestation(JsonNode node, String path) {
        Contract.number(node, path, 0, 100);
        return node.decimalValue();
    }

    public int acceptingProposerCount() {
        return proposerCount - rejectingProposerCount;
    }
}
