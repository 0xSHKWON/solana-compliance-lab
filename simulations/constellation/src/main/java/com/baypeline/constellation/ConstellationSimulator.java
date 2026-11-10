package com.baypeline.constellation;

import com.baypeline.constellation.model.Judgement;
import com.baypeline.constellation.model.MockDisplayModel;
import com.baypeline.constellation.model.ProtocolModel;
import com.baypeline.constellation.support.ApiException;
import com.baypeline.constellation.support.Contract;
import com.baypeline.constellation.support.StableIds;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * ConstellationSimulationRequest → ConstellationSimulationResult.
 *
 * <p>처리 순서
 * <ol>
 *   <li>구조 검증 (attestationPercent 0~100, 음수·타입 오류 → 400)</li>
 *   <li>protocolModelVersion 확인: 등록되지 않은 버전 → 422 UNSUPPORTED_VERSION</li>
 *   <li>구조상 유효하지만 모순된 시나리오 → INVALID_SCENARIO (모델과 무관한 정의상 모순만 검출)</li>
 *   <li>등록된 {@link ProtocolModel}에 판정 위임</li>
 * </ol>
 *
 * <p>attestationPercent 임계값, pslice 가용성과 포함 강제의 관계, 리더 제외 유효성,
 * 단일 리더 비교 규칙은 리서치 승인 전이므로 이 클래스에서 확정하지 않는다.
 */
@Component
public class ConstellationSimulator {

    private static final JsonNodeFactory JSON = JsonNodeFactory.instance;
    static final Set<String> EXPLANATIONS = Set.of("NO_ACCEPTING_PROPOSER", "NOT_SUBMITTED_TO_ACCEPTING_PROPOSER",
            "PSLICE_UNAVAILABLE", "ATTESTATION_CONDITION_NOT_MET", "ATTESTATION_CONDITION_MET",
            "LEADER_EXCLUSION_VALID", "LEADER_EXCLUSION_INVALID", "NO_EXCLUSION_ATTEMPT",
            "REJECTING_COUNT_EXCEEDS_TOTAL", "CONTRADICTORY_SUBMISSION_PATH", MockDisplayModel.EXPLANATION);

    private final Map<String, ProtocolModel> models;

    public ConstellationSimulator(ObjectProvider<ProtocolModel> approvedModels,
            @Value("${constellation.mock.enabled:false}") boolean mockEnabled,
            @Value("${constellation.mock.version:0.0.0-research-pending}") String mockVersion) {
        Map<String, ProtocolModel> registry = new LinkedHashMap<>();
        for (ProtocolModel model : approvedModels.orderedStream().toList()) {
            if (registry.put(model.version(), model) != null) {
                throw new IllegalStateException("Duplicate protocol model version " + model.version());
            }
        }
        if (mockEnabled) {
            registry.putIfAbsent(mockVersion, new MockDisplayModel(mockVersion));
        }
        this.models = Collections.unmodifiableMap(registry);
    }

    public List<String> supportedVersions() {
        return new ArrayList<>(models.keySet());
    }

    public ObjectNode simulate(JsonNode request) {
        Contract.object(request, "request",
                List.of("requestId", "intentId", "decisionId", "protocolModelVersion", "scenario"), List.of());
        Contract.id(request.get("requestId"), "request.requestId");
        String intentId = Contract.id(request.get("intentId"), "request.intentId");
        String decisionId = Contract.id(request.get("decisionId"), "request.decisionId");
        String version = Contract.version(request.get("protocolModelVersion"), "request.protocolModelVersion");
        Scenario scenario = Scenario.parse(request.get("scenario"), "request.scenario");

        ProtocolModel model = models.get(version);
        if (model == null) {
            throw ApiException.unsupportedVersion("protocolModelVersion " + version + " is not approved");
        }

        Judgement judgement = contradiction(scenario);
        if (judgement == null) {
            judgement = model.judge(scenario);
        }
        for (String code : judgement.explanationCodes()) {
            if (!EXPLANATIONS.contains(code)) {
                throw new IllegalStateException("Model returned unknown explanation code " + code);
            }
        }

        ObjectNode identity = JSON.objectNode();
        identity.put("intentId", intentId);
        identity.put("decisionId", decisionId);
        identity.put("protocolModelVersion", version);
        identity.set("scenario", request.get("scenario").deepCopy());

        ObjectNode result = JSON.objectNode();
        result.put("schemaVersion", Contract.SCHEMA_VERSION);
        result.put("simulationId", StableIds.of("simulation", identity));
        result.put("intentId", intentId);
        result.put("protocolModelVersion", version);
        result.put("proposerPathAvailable", judgement.proposerPathAvailable());
        result.put("psliceInclusionEnforced", judgement.psliceInclusionEnforced());
        if (judgement.leaderExclusionValid() == null) {
            result.putNull("leaderExclusionValid");
        } else {
            result.put("leaderExclusionValid", judgement.leaderExclusionValid());
        }
        result.put("outcome", judgement.outcome());
        ArrayNode codes = result.putArray("explanationCodes");
        judgement.explanationCodes().forEach(codes::add);
        result.put("simulationOnly", true);
        return result;
    }

    /**
     * 프로토콜 규칙과 무관하게 시나리오 자체가 성립하지 않는 경우.
     * 거절 제안자가 전체보다 많거나, 수락 제안자가 없는데 수락 제안자에게 제출했다고 하는 경우.
     */
    static Judgement contradiction(Scenario scenario) {
        if (scenario.rejectingProposerCount() > scenario.proposerCount()) {
            return new Judgement(false, false, null, "INVALID_SCENARIO", List.of("REJECTING_COUNT_EXCEEDS_TOTAL"));
        }
        if (scenario.submittedToAcceptingProposer() && scenario.acceptingProposerCount() == 0) {
            return new Judgement(false, false, null, "INVALID_SCENARIO", List.of("CONTRADICTORY_SUBMISSION_PATH"));
        }
        return null;
    }
}
