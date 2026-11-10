package com.baypeline.constellation.model;

import com.baypeline.constellation.Scenario;
import java.util.List;

/**
 * 비교 기준: 기존 단일 리더 모델.
 *
 * <p>리더 한 명이 블록 구성을 전적으로 결정하며 pslice·증명에 의한 포함 강제 장치가 없다.
 * 같은 시나리오를 Constellation 모델과 이 모델로 각각 실행해 통제 조건을 비교한다.
 * <ul>
 *   <li>제출 경로 판정은 Constellation 모델과 같다(비교 가능성을 위해).</li>
 *   <li>psliceInclusionEnforced는 항상 false, 경로가 있으면 INCLUSION_NOT_ENFORCED.</li>
 *   <li>리더의 제외 시도는 항상 규칙상 유효(LEADER_EXCLUSION_VALID).</li>
 *   <li>psliceAvailable·attestationPercent는 이 모델에 존재하지 않는 장치이므로 판정에 쓰지 않는다.</li>
 * </ul>
 */
public final class SingleLeaderBaselineModel implements ProtocolModel {

    private final String version;

    public SingleLeaderBaselineModel(String version) {
        this.version = version;
    }

    @Override
    public String version() {
        return version;
    }

    @Override
    public Judgement judge(Scenario scenario) {
        Judgement noPath = ProposerPath.check(scenario);
        if (noPath != null) {
            return noPath;
        }
        if (scenario.leaderAttemptsExclusion()) {
            return new Judgement(true, false, true, "INCLUSION_NOT_ENFORCED", List.of("LEADER_EXCLUSION_VALID"));
        }
        return new Judgement(true, false, null, "INCLUSION_NOT_ENFORCED", List.of("NO_EXCLUSION_ATTEMPT"));
    }
}
