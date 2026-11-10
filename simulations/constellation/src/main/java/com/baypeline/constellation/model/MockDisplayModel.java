package com.baypeline.constellation.model;

import com.baypeline.constellation.Scenario;
import java.util.List;

/**
 * 화면·스키마 연동 확인용 고정 출력 (contracts/fixtures/constellation/mock-result.json 과 같은 값).
 *
 * <p>프로토콜 판정이 아니다. 입력 시나리오의 수치로 결과를 계산하지 않으며 항상
 * MOCK_RESULT_NOT_PROTOCOL_VALIDATED 를 붙인다. 기본 비활성이며
 * {@code constellation.mock.enabled=true} 일 때만 mockVersion 요청에 응답한다.
 */
public final class MockDisplayModel implements ProtocolModel {

    public static final String EXPLANATION = "MOCK_RESULT_NOT_PROTOCOL_VALIDATED";

    private final String version;

    public MockDisplayModel(String version) {
        this.version = version;
    }

    @Override
    public String version() {
        return version;
    }

    @Override
    public Judgement judge(Scenario scenario) {
        return new Judgement(true, true, false, "INCLUSION_ENFORCED", List.of(EXPLANATION));
    }
}
