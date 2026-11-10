package com.baypeline.constellation.model;

import com.baypeline.constellation.Scenario;
import java.util.List;

/** 제안자 수락·거절 경로 판정. 경로가 없으면 NO_SUBMISSION_PATH 판정을, 있으면 null을 반환한다. */
final class ProposerPath {

    private ProposerPath() {
    }

    static Judgement check(Scenario scenario) {
        if (scenario.acceptingProposerCount() == 0) {
            return new Judgement(false, false, null, "NO_SUBMISSION_PATH", List.of("NO_ACCEPTING_PROPOSER"));
        }
        if (!scenario.submittedToAcceptingProposer()) {
            return new Judgement(false, false, null, "NO_SUBMISSION_PATH",
                    List.of("NOT_SUBMITTED_TO_ACCEPTING_PROPOSER"));
        }
        return null;
    }
}
