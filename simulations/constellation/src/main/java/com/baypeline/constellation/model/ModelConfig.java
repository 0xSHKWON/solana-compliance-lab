package com.baypeline.constellation.model;

import java.math.BigDecimal;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** 시뮬레이션 모델 등록. 각 모델은 버전으로 고정되며 요청의 protocolModelVersion으로 선택된다. */
@Configuration
@ConditionalOnProperty(name = "constellation.models.enabled", havingValue = "true", matchIfMissing = true)
public class ModelConfig {

    @Bean
    ProtocolModel constellationDraftModel(
            @Value("${constellation.models.draft.version}") String version,
            @Value("${constellation.models.draft.attestation-threshold-percent}") BigDecimal threshold) {
        return new ConstellationDraftModel(version, threshold);
    }

    @Bean
    ProtocolModel singleLeaderBaselineModel(@Value("${constellation.models.baseline.version}") String version) {
        return new SingleLeaderBaselineModel(version);
    }
}
