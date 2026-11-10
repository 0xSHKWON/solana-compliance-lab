package com.baypeline.constellation.model;

import com.baypeline.constellation.Scenario;

/**
 * 리서치팀이 승인한 Constellation 프로토콜 판정 모델.
 *
 * <p>승인 시 출처·파라미터·버전·검증 시나리오를 함께 등록한다. 구현체를 Spring Bean으로 추가하면
 * 해당 {@link #version()}이 자동으로 지원 목록에 들어간다. 현재 승인된 모델은 없다
 * (contracts/config/protocol-models.json: approvedVersions = []).
 */
public interface ProtocolModel {

    /** 고정된 SemVer. 예: "1.0.0". */
    String version();

    /**
     * 구조상 유효하고 모순이 없는 시나리오만 전달된다(INVALID_SCENARIO는 상위에서 처리).
     * 같은 시나리오는 항상 같은 결과를 반환해야 한다.
     */
    Judgement judge(Scenario scenario);
}
