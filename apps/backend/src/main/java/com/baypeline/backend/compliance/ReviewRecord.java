package com.baypeline.backend.compliance;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.Instant;

/**
 * 정책 심사 기록. Gateway·Constellation 실험은 이 기록의 intent·decision을 사용한다.
 * 브라우저가 보낸 위험 점수나 정책 Action은 신뢰하지 않는다.
 */
public record ReviewRecord(
        String decisionId,
        String intentId,
        String requestId,
        String senderAnalysisId,
        String recipientAnalysisId,
        JsonNode intent,
        JsonNode assessments,
        JsonNode decision,
        Instant createdAt) {
}
