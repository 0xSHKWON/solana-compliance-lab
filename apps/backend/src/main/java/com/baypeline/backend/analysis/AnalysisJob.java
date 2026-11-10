package com.baypeline.backend.analysis;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.time.Instant;

/**
 * 분석 작업 상태. 상태 전이: QUEUED → RUNNING → COMPLETED/PARTIAL/FAILED, QUEUED → FAILED.
 * 종료 상태의 재시도는 새 analysisId로 추적한다. 불변 객체이며 전이마다 새 인스턴스를 저장한다.
 *
 * @param snapshot   Collector가 반환한 KYTDataSnapshot (Snapshot 저장 단계 이후)
 * @param evaluation KYT Engine이 반환한 KYTEvaluation
 * @param error      FAILED일 때 {code, message, retryable}
 */
public record AnalysisJob(
        String analysisId,
        String requestId,
        JobStatus status,
        String address,
        String mode,
        String fixtureId,
        JsonNode scope,
        String rulesetVersion,
        Instant createdAt,
        Instant updatedAt,
        JsonNode snapshot,
        JsonNode evaluation,
        ObjectNode error) {

    public enum JobStatus {
        QUEUED, RUNNING, COMPLETED, PARTIAL, FAILED;

        public boolean terminal() {
            return this == COMPLETED || this == PARTIAL || this == FAILED;
        }

        /** Snapshot과 평가 결과가 공개된 상태. */
        public boolean hasResult() {
            return this == COMPLETED || this == PARTIAL;
        }
    }

    public AnalysisJob running(Instant now) {
        requireState(status == JobStatus.QUEUED, JobStatus.RUNNING);
        return new AnalysisJob(analysisId, requestId, JobStatus.RUNNING, address, mode, fixtureId, scope,
                rulesetVersion, createdAt, now, null, null, null);
    }

    /** Snapshot 저장 단계. 상태는 RUNNING을 유지하며 조회 응답에는 아직 노출하지 않는다. */
    public AnalysisJob withSnapshot(JsonNode collected, Instant now) {
        requireState(status == JobStatus.RUNNING, JobStatus.RUNNING);
        return new AnalysisJob(analysisId, requestId, status, address, mode, fixtureId, scope, rulesetVersion,
                createdAt, now, collected, null, null);
    }

    public AnalysisJob finished(JobStatus result, JsonNode kytEvaluation, Instant now) {
        requireState(status == JobStatus.RUNNING && snapshot != null && result.hasResult(), result);
        return new AnalysisJob(analysisId, requestId, result, address, mode, fixtureId, scope, rulesetVersion,
                createdAt, now, snapshot, kytEvaluation, null);
    }

    /** 실패 전 저장된 Snapshot은 내부에 보존하지만 조회 응답에는 노출하지 않는다. */
    public AnalysisJob failed(ObjectNode failure, Instant now) {
        requireState(!status.terminal(), JobStatus.FAILED);
        return new AnalysisJob(analysisId, requestId, JobStatus.FAILED, address, mode, fixtureId, scope,
                rulesetVersion, createdAt, now, snapshot, null, failure);
    }

    private void requireState(boolean condition, JobStatus target) {
        if (!condition) {
            throw new IllegalStateException("Invalid transition " + status + " -> " + target);
        }
    }
}
