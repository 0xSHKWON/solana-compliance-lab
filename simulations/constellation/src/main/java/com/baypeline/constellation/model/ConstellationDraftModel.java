package com.baypeline.constellation.model;

import com.baypeline.constellation.Scenario;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * Constellation 거래 포함 규칙 초안 모델 (다중 제안자 + pslice + 증명).
 *
 * <p>판정 순서
 * <ol>
 *   <li><b>제안자 경로</b>: 수락 제안자 수 = proposerCount - rejectingProposerCount.
 *       0이면 NO_ACCEPTING_PROPOSER, 수락 제안자에게 제출하지 않았으면 NOT_SUBMITTED_TO_ACCEPTING_PROPOSER
 *       → NO_SUBMISSION_PATH.</li>
 *   <li><b>pslice 가용성</b>: 거래를 담은 pslice가 가용하지 않으면 PSLICE_UNAVAILABLE → 포함 강제 불가.</li>
 *   <li><b>증명 조건</b>: attestationPercent ≥ 임계값이면 ATTESTATION_CONDITION_MET → 포함 강제,
 *       미만이면 ATTESTATION_CONDITION_NOT_MET.</li>
 *   <li><b>리더 제외</b>: 제외 시도가 없으면 null / NO_EXCLUSION_ATTEMPT.
 *       포함이 강제된 pslice를 제외하려 하면 LEADER_EXCLUSION_INVALID(false),
 *       강제되지 않은 경우 제외는 규칙상 허용되어 LEADER_EXCLUSION_VALID(true).</li>
 * </ol>
 *
 * <p>제출 경로가 없으면 제외할 대상 거래가 없으므로 leaderExclusionValid는 null이다.
 * 임계값은 설정({@code constellation.models.draft.attestation-threshold-percent})으로 고정하며,
 * 리서치팀이 공식 설계를 확정하면 값 또는 버전을 갱신한다. 포함 확률이나 제재 우회 성공률은 계산하지 않는다.
 */
public final class ConstellationDraftModel implements ProtocolModel {

    private final String version;
    private final BigDecimal attestationThresholdPercent;

    public ConstellationDraftModel(String version, BigDecimal attestationThresholdPercent) {
        if (attestationThresholdPercent.signum() < 0 || attestationThresholdPercent.compareTo(BigDecimal.valueOf(100)) > 0) {
            throw new IllegalArgumentException("attestation threshold must be within 0..100");
        }
        this.version = version;
        this.attestationThresholdPercent = attestationThresholdPercent;
    }

    @Override
    public String version() {
        return version;
    }

    public BigDecimal attestationThresholdPercent() {
        return attestationThresholdPercent;
    }

    @Override
    public Judgement judge(Scenario scenario) {
        Judgement noPath = ProposerPath.check(scenario);
        if (noPath != null) {
            return noPath;
        }
        List<String> codes = new ArrayList<>();
        boolean enforced;
        if (!scenario.psliceAvailable()) {
            codes.add("PSLICE_UNAVAILABLE");
            enforced = false;
        } else if (scenario.attestationPercent().compareTo(attestationThresholdPercent) >= 0) {
            codes.add("ATTESTATION_CONDITION_MET");
            enforced = true;
        } else {
            codes.add("ATTESTATION_CONDITION_NOT_MET");
            enforced = false;
        }

        Boolean exclusionValid;
        if (!scenario.leaderAttemptsExclusion()) {
            codes.add("NO_EXCLUSION_ATTEMPT");
            exclusionValid = null;
        } else if (enforced) {
            codes.add("LEADER_EXCLUSION_INVALID");
            exclusionValid = false;
        } else {
            codes.add("LEADER_EXCLUSION_VALID");
            exclusionValid = true;
        }
        return new Judgement(true, enforced, exclusionValid,
                enforced ? "INCLUSION_ENFORCED" : "INCLUSION_NOT_ENFORCED", codes);
    }
}
