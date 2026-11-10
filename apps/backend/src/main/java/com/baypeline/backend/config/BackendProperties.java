package com.baypeline.backend.config;

import java.time.Duration;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

/** application.yml 의 compliance.* 설정. */
@ConfigurationProperties("compliance")
public record BackendProperties(
        String defaultRulesetVersion,
        boolean async,
        int analysisWorkers,
        int analysisQueueCapacity,
        List<String> corsAllowedOrigins,
        Upstream upstream,
        LocalCollector localCollector) {

    public record Upstream(
            String collectorUrl,
            String kytUrl,
            String policyUrl,
            String gatewayUrl,
            String constellationUrl,
            Duration connectTimeout,
            Duration readTimeout) {
    }

    /** 로컬 개발 전용: Collector 대신 contracts/fixtures 의 Snapshot 파일을 반환한다. */
    public record LocalCollector(boolean enabled, String fixturesDir) {
    }
}
