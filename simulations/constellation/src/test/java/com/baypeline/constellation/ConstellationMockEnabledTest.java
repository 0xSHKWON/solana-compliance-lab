package com.baypeline.constellation;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
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

/** constellation.mock.enabled=true: 화면 확인용 고정 결과. */
@SpringBootTest(properties = "constellation.mock.enabled=true")
@AutoConfigureMockMvc
class ConstellationMockEnabledTest {

    @Autowired
    MockMvc mvc;

    @Autowired
    ObjectMapper mapper;

    @Test
    void returnsMockDisplayResultMarkedAsNotValidated() throws Exception {
        JsonNode request = Fixtures.fixture(mapper, "mock-request.json");
        JsonNode expected = Fixtures.fixture(mapper, "mock-result.json");
        JsonNode actual = read(simulate(request).andExpect(status().isOk()));

        for (String field : new String[] {"schemaVersion", "intentId", "protocolModelVersion",
                "proposerPathAvailable", "psliceInclusionEnforced", "leaderExclusionValid", "outcome",
                "explanationCodes", "simulationOnly"}) {
            assertThat(actual.get(field)).as(field).isEqualTo(expected.get(field));
        }
        assertThat(actual.get("simulationId").textValue()).startsWith("simulation-");
    }

    @Test
    void sameScenarioIsReproducible() throws Exception {
        ObjectNode request = (ObjectNode) Fixtures.fixture(mapper, "mock-request.json");
        JsonNode first = read(simulate(request));
        request.put("requestId", "another");
        JsonNode second = read(simulate(request));
        assertThat(first).isEqualTo(second);
    }

    @Test
    void rejectingCountAboveTotalIsInvalidScenario() throws Exception {
        ObjectNode request = (ObjectNode) Fixtures.fixture(mapper, "mock-request.json");
        ((ObjectNode) request.get("scenario")).put("rejectingProposerCount", 5);
        simulate(request)
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.outcome").value("INVALID_SCENARIO"))
                .andExpect(jsonPath("$.proposerPathAvailable").value(false))
                .andExpect(jsonPath("$.psliceInclusionEnforced").value(false))
                .andExpect(jsonPath("$.leaderExclusionValid").isEmpty())
                .andExpect(jsonPath("$.explanationCodes[0]").value("REJECTING_COUNT_EXCEEDS_TOTAL"));
    }

    @Test
    void submittingToAcceptingProposerWhenAllRejectIsInvalidScenario() throws Exception {
        ObjectNode request = (ObjectNode) Fixtures.fixture(mapper, "mock-request.json");
        ((ObjectNode) request.get("scenario")).put("rejectingProposerCount", 4);
        simulate(request)
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.outcome").value("INVALID_SCENARIO"))
                .andExpect(jsonPath("$.explanationCodes[0]").value("CONTRADICTORY_SUBMISSION_PATH"));
    }

    @Test
    void otherVersionsStill422() throws Exception {
        ObjectNode request = (ObjectNode) Fixtures.fixture(mapper, "mock-request.json");
        request.put("protocolModelVersion", "1.0.0");
        simulate(request).andExpect(status().isUnprocessableEntity());
    }

    private ResultActions simulate(JsonNode request) throws Exception {
        return mvc.perform(post(Fixtures.PATH).contentType(MediaType.APPLICATION_JSON).content(request.toString()));
    }

    private JsonNode read(ResultActions actions) throws Exception {
        return mapper.readTree(actions.andReturn().getResponse().getContentAsString());
    }
}
