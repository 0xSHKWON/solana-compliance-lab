package com.baypeline.constellation;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

/** HTTP 경계에서 초안·단일 리더 모델 실행과 재현성. */
@SpringBootTest
@AutoConfigureMockMvc
class ConstellationModelApiTest {

    @Autowired
    MockMvc mvc;

    @Autowired
    ObjectMapper mapper;

    @Test
    void draftModelEnforcesInclusionForAttestedPslice() throws Exception {
        simulate(request("0.1.0-draft"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.protocolModelVersion").value("0.1.0-draft"))
                .andExpect(jsonPath("$.outcome").value("INCLUSION_ENFORCED"))
                .andExpect(jsonPath("$.proposerPathAvailable").value(true))
                .andExpect(jsonPath("$.psliceInclusionEnforced").value(true))
                .andExpect(jsonPath("$.leaderExclusionValid").value(false))
                .andExpect(jsonPath("$.explanationCodes[0]").value("ATTESTATION_CONDITION_MET"))
                .andExpect(jsonPath("$.explanationCodes[1]").value("LEADER_EXCLUSION_INVALID"))
                .andExpect(jsonPath("$.simulationOnly").value(true));
    }

    @Test
    void baselineComparisonOnSameScenario() throws Exception {
        simulate(request("0.1.0-single-leader"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.outcome").value("INCLUSION_NOT_ENFORCED"))
                .andExpect(jsonPath("$.leaderExclusionValid").value(true));
    }

    @Test
    void invalidScenarioCheckedBeforeModel() throws Exception {
        ObjectNode request = request("0.1.0-draft");
        ((ObjectNode) request.get("scenario")).put("rejectingProposerCount", 5);
        simulate(request).andExpect(jsonPath("$.outcome").value("INVALID_SCENARIO"));
    }

    @Test
    void reproducibleAcrossRequestIds() throws Exception {
        ObjectNode request = request("0.1.0-draft");
        JsonNode first = read(simulate(request));
        request.put("requestId", "other-request");
        assertThat(read(simulate(request))).isEqualTo(first);
    }

    private ObjectNode request(String version) throws Exception {
        ObjectNode request = (ObjectNode) Fixtures.fixture(mapper, "mock-request.json");
        request.put("protocolModelVersion", version);
        return request;
    }

    private ResultActions simulate(JsonNode request) throws Exception {
        return mvc.perform(post(Fixtures.PATH).contentType(MediaType.APPLICATION_JSON).content(request.toString()));
    }

    private JsonNode read(ResultActions actions) throws Exception {
        return mapper.readTree(actions.andReturn().getResponse().getContentAsString());
    }
}
