package com.baypeline.constellation.model;

import java.util.List;

/**
 * 프로토콜 모델의 판정 결과. outcome과 boolean 필드의 조합은 experiment.schema.json 의 allOf 규칙을 따라야 한다.
 *
 * @param leaderExclusionValid 제외 시도가 없으면 null
 */
public record Judgement(
        boolean proposerPathAvailable,
        boolean psliceInclusionEnforced,
        Boolean leaderExclusionValid,
        String outcome,
        List<String> explanationCodes) {

    public Judgement {
        explanationCodes = List.copyOf(explanationCodes);
        if (explanationCodes.isEmpty()) {
            throw new IllegalArgumentException("explanationCodes must not be empty");
        }
        switch (outcome) {
            case "INCLUSION_ENFORCED" -> require(proposerPathAvailable && psliceInclusionEnforced, outcome);
            case "NO_SUBMISSION_PATH" -> require(!proposerPathAvailable && !psliceInclusionEnforced, outcome);
            case "INCLUSION_NOT_ENFORCED" -> require(!psliceInclusionEnforced, outcome);
            case "INVALID_SCENARIO" -> require(!proposerPathAvailable && !psliceInclusionEnforced
                    && leaderExclusionValid == null, outcome);
            default -> throw new IllegalArgumentException("Unknown outcome " + outcome);
        }
    }

    private static void require(boolean condition, String outcome) {
        if (!condition) {
            throw new IllegalArgumentException("Field combination violates contract for " + outcome);
        }
    }
}
