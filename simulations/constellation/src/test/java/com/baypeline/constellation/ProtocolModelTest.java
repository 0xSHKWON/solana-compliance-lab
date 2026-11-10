package com.baypeline.constellation;

import static org.assertj.core.api.Assertions.assertThat;

import com.baypeline.constellation.model.ConstellationDraftModel;
import com.baypeline.constellation.model.Judgement;
import com.baypeline.constellation.model.SingleLeaderBaselineModel;
import java.math.BigDecimal;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

/** 판정 규칙 단위 테스트. */
class ProtocolModelTest {

    final ConstellationDraftModel draft = new ConstellationDraftModel("0.1.0-draft", new BigDecimal("66.67"));
    final SingleLeaderBaselineModel baseline = new SingleLeaderBaselineModel("0.1.0-single-leader");

    static Scenario scenario(int proposers, int rejecting, boolean submitted, boolean pslice, String attestation,
            boolean exclusion) {
        return new Scenario(proposers, rejecting, submitted, pslice, new BigDecimal(attestation), exclusion);
    }

    @ParameterizedTest(name = "{0}")
    @CsvSource(delimiter = '|', textBlock = """
            # 이름                       |P|R|submit|pslice|attest|excl |path |enforced|exclValid|outcome               |codes
            모든 제안자 거절              |4|4|false |true  |100   |true |false|false   |         |NO_SUBMISSION_PATH    |NO_ACCEPTING_PROPOSER
            수락 제안자에 미제출          |4|1|false |true  |100   |false|false|false   |         |NO_SUBMISSION_PATH    |NOT_SUBMITTED_TO_ACCEPTING_PROPOSER
            pslice 불가 + 제외 시도       |4|1|true  |false |100   |true |true |false   |true     |INCLUSION_NOT_ENFORCED|PSLICE_UNAVAILABLE,LEADER_EXCLUSION_VALID
            증명 미달 + 제외 시도         |4|1|true  |true  |50    |true |true |false   |true     |INCLUSION_NOT_ENFORCED|ATTESTATION_CONDITION_NOT_MET,LEADER_EXCLUSION_VALID
            증명 미달 + 시도 없음         |4|1|true  |true  |66.66 |false|true |false   |         |INCLUSION_NOT_ENFORCED|ATTESTATION_CONDITION_NOT_MET,NO_EXCLUSION_ATTEMPT
            임계값 정확히 충족            |4|1|true  |true  |66.67 |false|true |true    |         |INCLUSION_ENFORCED    |ATTESTATION_CONDITION_MET,NO_EXCLUSION_ATTEMPT
            포함 강제 + 리더 제외 시도    |4|1|true  |true  |100   |true |true |true    |false    |INCLUSION_ENFORCED    |ATTESTATION_CONDITION_MET,LEADER_EXCLUSION_INVALID
            """)
    void draftRules(String name, int p, int r, boolean submitted, boolean pslice, String attestation,
            boolean exclusion, boolean path, boolean enforced, Boolean exclusionValid, String outcome, String codes) {
        Judgement j = draft.judge(scenario(p, r, submitted, pslice, attestation, exclusion));
        assertThat(j.proposerPathAvailable()).isEqualTo(path);
        assertThat(j.psliceInclusionEnforced()).isEqualTo(enforced);
        assertThat(j.leaderExclusionValid()).isEqualTo(exclusionValid);
        assertThat(j.outcome()).isEqualTo(outcome);
        assertThat(String.join(",", j.explanationCodes())).isEqualTo(codes);
    }

    @Test
    void baselineNeverEnforcesAndAlwaysAllowsExclusion() {
        Judgement j = baseline.judge(scenario(4, 1, true, true, "100", true));
        assertThat(j.outcome()).isEqualTo("INCLUSION_NOT_ENFORCED");
        assertThat(j.psliceInclusionEnforced()).isFalse();
        assertThat(j.leaderExclusionValid()).isTrue();
        assertThat(j.explanationCodes()).containsExactly("LEADER_EXCLUSION_VALID");

        assertThat(baseline.judge(scenario(4, 1, true, true, "100", false)).leaderExclusionValid()).isNull();
        assertThat(baseline.judge(scenario(4, 4, false, true, "100", true)).outcome())
                .isEqualTo("NO_SUBMISSION_PATH");
    }

    @Test
    void sameScenarioDiffersOnlyByEnforcementMechanism() {
        Scenario s = scenario(4, 1, true, true, "100", true);
        assertThat(draft.judge(s).outcome()).isEqualTo("INCLUSION_ENFORCED");
        assertThat(baseline.judge(s).outcome()).isEqualTo("INCLUSION_NOT_ENFORCED");
        assertThat(draft.judge(s).leaderExclusionValid()).isFalse();
        assertThat(baseline.judge(s).leaderExclusionValid()).isTrue();
    }
}
