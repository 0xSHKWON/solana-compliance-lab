package com.baypeline.backend.analysis;

import com.baypeline.backend.analysis.AnalysisJob.JobStatus;
import com.baypeline.backend.config.BackendProperties;
import com.baypeline.backend.support.ApiContracts;
import com.baypeline.backend.support.ApiException;
import com.baypeline.backend.support.Contract;
import com.baypeline.backend.upstream.UpstreamException;
import com.baypeline.backend.upstream.UpstreamServices;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Base64;
import java.util.UUID;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.task.TaskExecutor;
import org.springframework.core.task.TaskRejectedException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

/**
 * 분석 작업 오케스트레이션: 작업 생성 → Collector 호출 → Snapshot 저장 → KYT 호출 → 평가 저장.
 * 위험도를 직접 계산하거나 Collector의 정규화를 반복하지 않는다. 내부 모듈 응답은 핵심 연결 관계를
 * 검증한 뒤에만 저장·노출한다.
 */
@Service
public class AnalysisService {

    private static final Logger log = LoggerFactory.getLogger(AnalysisService.class);
    private static final JsonNodeFactory JSON = JsonNodeFactory.instance;
    private static final Pattern LIMIT = Pattern.compile("^[1-9][0-9]{0,3}$");
    static final int DEFAULT_LIMIT = 100;
    static final int MAX_LIMIT = 1000;

    private final AnalysisRepository repository;
    private final UpstreamServices upstream;
    private final TaskExecutor executor;
    private final BackendProperties properties;
    private final Clock clock;

    public AnalysisService(AnalysisRepository repository, UpstreamServices upstream, TaskExecutor analysisExecutor,
            BackendProperties properties, Clock clock) {
        this.repository = repository;
        this.upstream = upstream;
        this.executor = analysisExecutor;
        this.properties = properties;
        this.clock = clock;
    }

    /** POST /api/v1/analyses → 202 AnalysisAccepted. */
    public ObjectNode create(JsonNode request, String requestId) {
        ApiContracts.analysisRequest(request);
        Instant now = now();
        String rulesetVersion = request.has("rulesetVersion")
                ? request.get("rulesetVersion").textValue()
                : properties.defaultRulesetVersion();
        AnalysisJob job = new AnalysisJob("analysis-" + UUID.randomUUID(), requestId, JobStatus.QUEUED,
                request.get("address").textValue(), request.get("mode").textValue(),
                request.has("fixtureId") ? request.get("fixtureId").textValue() : null,
                request.get("scope").deepCopy(), rulesetVersion, now, now, null, null, null);
        repository.save(job);
        try {
            executor.execute(() -> run(job.analysisId()));
        } catch (TaskRejectedException e) {
            repository.delete(job.analysisId());
            throw new ApiException(HttpStatus.TOO_MANY_REQUESTS, "RATE_LIMITED", "Too many running analyses", true);
        }
        ObjectNode accepted = JSON.objectNode();
        accepted.put("schemaVersion", Contract.SCHEMA_VERSION);
        accepted.put("analysisId", job.analysisId());
        accepted.put("requestId", requestId);
        accepted.put("status", JobStatus.QUEUED.name());
        return accepted;
    }

    void run(String analysisId) {
        AnalysisJob job = repository.find(analysisId).orElse(null);
        if (job == null || job.status() != JobStatus.QUEUED) {
            return;
        }
        job = job.running(now());
        repository.save(job);
        try {
            JsonNode snapshot = upstream.collect(job.requestId(), collectionRequest(job));
            checkSnapshot(job, snapshot);
            job = job.withSnapshot(snapshot, now());
            repository.save(job);

            ObjectNode kytRequest = JSON.objectNode();
            kytRequest.put("requestId", job.requestId());
            kytRequest.set("snapshot", snapshot);
            kytRequest.put("rulesetVersion", job.rulesetVersion());
            JsonNode evaluation = upstream.evaluateKyt(job.requestId(), kytRequest);
            JobStatus result = checkEvaluation(job, snapshot, evaluation);
            repository.save(job.finished(result, evaluation, now()));
        } catch (UpstreamException e) {
            repository.save(job.failed(error(e.jobErrorCode(), e.publicMessage(), e.retryable()), now()));
        } catch (ApiException e) {
            repository.save(job.failed(error(e.code(), e.getMessage(), e.retryable()), now()));
        } catch (RuntimeException e) {
            log.error("Analysis {} failed unexpectedly", analysisId, e);
            repository.save(job.failed(error("INTERNAL_ERROR", "Analysis failed", false), now()));
        }
    }

    /** GET /api/v1/analyses/{id} → KYTAnalysisResult. 작업이 있으면 FAILED도 200. */
    public ObjectNode get(String analysisId) {
        return result(find(analysisId));
    }

    /** GET /api/v1/analyses/{id}/transfers → TransferPage. */
    public ObjectNode transfers(String analysisId, String limitParam, String cursor) {
        int limit = limit(limitParam);
        AnalysisJob job = find(analysisId);
        if (!job.status().hasResult()) {
            throw new ApiException(HttpStatus.CONFLICT, "ANALYSIS_NOT_READY",
                    "Snapshot is not available for status " + job.status(), job.status() != JobStatus.FAILED);
        }
        String snapshotId = job.snapshot().get("snapshotId").textValue();
        JsonNode transfers = job.snapshot().get("transfers");
        int offset = cursor == null ? 0 : decodeCursor(cursor, snapshotId, transfers.size());
        int end = Math.min(offset + limit, transfers.size());

        ObjectNode page = JSON.objectNode();
        page.put("schemaVersion", Contract.SCHEMA_VERSION);
        page.put("analysisId", job.analysisId());
        page.put("snapshotId", snapshotId);
        ArrayNode items = page.putArray("items");
        for (int i = offset; i < end; i++) {
            items.add(transfers.get(i));
        }
        ObjectNode pagination = page.putObject("pagination");
        pagination.put("limit", limit);
        if (end < transfers.size()) {
            pagination.put("nextCursor", encodeCursor(snapshotId, end));
        } else {
            pagination.putNull("nextCursor");
        }
        return page;
    }

    public AnalysisJob find(String analysisId) {
        return repository.find(analysisId).orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND",
                "Analysis not found", false));
    }

    static ObjectNode result(AnalysisJob job) {
        ObjectNode node = JSON.objectNode();
        node.put("schemaVersion", Contract.SCHEMA_VERSION);
        node.put("analysisId", job.analysisId());
        node.put("requestId", job.requestId());
        node.put("status", job.status().name());
        node.put("address", job.address());
        node.put("network", "mainnet-beta");
        node.put("mode", job.mode());
        node.put("createdAt", job.createdAt().toString());
        node.put("updatedAt", job.updatedAt().toString());
        if (job.status().hasResult()) {
            node.put("snapshotId", job.snapshot().get("snapshotId").textValue());
            node.set("coverage", job.snapshot().get("coverage"));
            node.set("dataProvenance", job.snapshot().get("dataProvenance"));
            node.set("evaluation", job.evaluation());
        } else {
            node.putNull("snapshotId");
            node.putNull("coverage");
            node.putNull("dataProvenance");
            node.putNull("evaluation");
        }
        if (job.status() == JobStatus.FAILED) {
            node.set("error", job.error());
        } else {
            node.putNull("error");
        }
        return node;
    }

    private static ObjectNode collectionRequest(AnalysisJob job) {
        ObjectNode request = JSON.objectNode();
        request.put("requestId", job.requestId());
        request.put("address", job.address());
        request.put("network", "mainnet-beta");
        request.put("mode", job.mode());
        if (job.fixtureId() != null) {
            request.put("fixtureId", job.fixtureId());
        }
        request.set("scope", job.scope());
        return request;
    }

    /** Snapshot이 이 작업의 요청에 대한 응답인지 확인한다. 세부 구조는 Collector가 계약대로 검증한다. */
    private static void checkSnapshot(AnalysisJob job, JsonNode snapshot) {
        String problem = null;
        JsonNode coverage = snapshot.path("coverage");
        if (!Contract.SCHEMA_VERSION.equals(snapshot.path("schemaVersion").asText())) {
            problem = "unsupported schemaVersion";
        } else if (!snapshot.path("snapshotId").isTextual() || snapshot.get("snapshotId").textValue().isEmpty()) {
            problem = "missing snapshotId";
        } else if (!job.requestId().equals(snapshot.path("requestId").asText())) {
            problem = "requestId mismatch";
        } else if (!job.address().equals(snapshot.path("address").asText())) {
            problem = "address mismatch";
        } else if (!job.mode().equals(snapshot.path("mode").asText())) {
            problem = "mode mismatch";
        } else if (!"mainnet-beta".equals(snapshot.path("network").asText())) {
            problem = "network mismatch";
        } else if (!snapshot.path("transfers").isArray() || !snapshot.path("labels").isArray()) {
            problem = "transfers/labels must be arrays";
        } else if (!coverage.isObject() || !("COMPLETE".equals(coverage.path("status").asText())
                || "PARTIAL".equals(coverage.path("status").asText()))) {
            problem = "invalid coverage";
        } else if (coverage.path("transferCount").asInt(-1) != snapshot.get("transfers").size()) {
            problem = "coverage.transferCount does not match transfers";
        } else if (!snapshot.path("dataProvenance").isObject()) {
            problem = "missing dataProvenance";
        } else if ("LIVE".equals(job.mode())
                && !"ON_CHAIN".equals(snapshot.path("dataProvenance").path("dataType").asText())) {
            problem = "LIVE snapshot must be ON_CHAIN";
        }
        if (problem != null) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "CONTRACT_VALIDATION_FAILED",
                    "collector returned an inconsistent snapshot: " + problem, false);
        }
    }

    /** 평가가 저장된 Snapshot에 대한 것인지와 coverage에 맞는 점수 형태인지 확인한다. 점수를 다시 계산하지 않는다. */
    private static JobStatus checkEvaluation(AnalysisJob job, JsonNode snapshot, JsonNode evaluation) {
        boolean complete = "COMPLETE".equals(snapshot.get("coverage").get("status").asText());
        JsonNode score = evaluation.path("riskScore");
        JsonNode level = evaluation.path("riskLevel");
        String problem = null;
        if (!Contract.SCHEMA_VERSION.equals(evaluation.path("schemaVersion").asText())) {
            problem = "unsupported schemaVersion";
        } else if (!job.address().equals(evaluation.path("subjectAddress").asText())) {
            problem = "subjectAddress mismatch";
        } else if (!snapshot.get("snapshotId").asText().equals(evaluation.path("snapshotId").asText())) {
            problem = "snapshotId mismatch";
        } else if (!job.rulesetVersion().equals(evaluation.path("rulesetVersion").asText())) {
            problem = "rulesetVersion mismatch";
        } else if (!evaluation.path("detectedRules").isArray() || !evaluation.path("evidences").isArray()) {
            problem = "detectedRules/evidences must be arrays";
        } else if (complete && !(score.isIntegralNumber() && level.isTextual())) {
            problem = "complete coverage requires a numeric riskScore";
        } else if (!complete && !(score.isNull() && level.isNull())) {
            problem = "partial coverage requires null riskScore and riskLevel";
        }
        if (problem != null) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "CONTRACT_VALIDATION_FAILED",
                    "kyt-engine returned an inconsistent evaluation: " + problem, false);
        }
        return complete ? JobStatus.COMPLETED : JobStatus.PARTIAL;
    }

    private static int limit(String value) {
        if (value == null) {
            return DEFAULT_LIMIT;
        }
        if (!LIMIT.matcher(value).matches() || Integer.parseInt(value) > MAX_LIMIT) {
            throw ApiException.invalid("limit must be an integer between 1 and " + MAX_LIMIT);
        }
        return Integer.parseInt(value);
    }

    /** 불투명 cursor: base64url("v1:{snapshotId}:{offset}"). 다른 Snapshot의 cursor는 거부한다. */
    static String encodeCursor(String snapshotId, int offset) {
        String raw = "v1:" + snapshotId + ":" + offset;
        return Base64.getUrlEncoder().withoutPadding().encodeToString(raw.getBytes(StandardCharsets.UTF_8));
    }

    private static int decodeCursor(String cursor, String snapshotId, int size) {
        try {
            String raw = new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8);
            String prefix = "v1:" + snapshotId + ":";
            if (raw.startsWith(prefix)) {
                int offset = Integer.parseInt(raw.substring(prefix.length()));
                if (offset > 0 && offset < size) {
                    return offset;
                }
            }
        } catch (IllegalArgumentException e) {
            // fall through
        }
        throw ApiException.invalid("Invalid cursor");
    }

    private static ObjectNode error(String code, String message, boolean retryable) {
        ObjectNode error = JSON.objectNode();
        error.put("code", code);
        error.put("message", message == null || message.isEmpty() ? "Analysis failed" : message);
        error.put("retryable", retryable);
        return error;
    }

    private Instant now() {
        return clock.instant().truncatedTo(ChronoUnit.MILLIS);
    }
}
