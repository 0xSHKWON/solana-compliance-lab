package com.baypeline.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.IOException;
import java.io.InputStream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

@SpringBootTest
@AutoConfigureMockMvc
class GatewayControllerTest {

    private static final String PATH = "/internal/v1/gateway/experiment";

    @Autowired
    MockMvc mvc;

    @Autowired
    ObjectMapper mapper;

    /** contracts/fixtures/gateway 의 요청을 넣으면 같은 outcome·reasonCodes가 나와야 한다. */
    @ParameterizedTest
    @ValueSource(strings = {"allow", "block", "review", "warning-acknowledged", "warning-unacknowledged",
            "alternative-path"})
    void matchesContractFixtures(String scenario) throws Exception {
        JsonNode request = fixture(scenario + "-request.json");
        JsonNode expected = fixture(scenario + "-result.json");

        MvcResult result = mvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON)
                        .content(request.toString()))
                .andExpect(status().isOk())
                .andExpect(header().string("X-Request-ID", request.get("requestId").textValue()))
                .andReturn();
        JsonNode actual = mapper.readTree(result.getResponse().getContentAsString());

        assertThat(actual.get("schemaVersion")).isEqualTo(expected.get("schemaVersion"));
        assertThat(actual.get("intentId")).isEqualTo(expected.get("intentId"));
        assertThat(actual.get("routeId")).isEqualTo(expected.get("routeId"));
        assertThat(actual.get("outcome")).isEqualTo(expected.get("outcome"));
        assertThat(actual.get("policyApplied")).isEqualTo(expected.get("policyApplied"));
        assertThat(actual.get("reasonCodes")).isEqualTo(expected.get("reasonCodes"));
        assertThat(actual.get("actualBroadcast").booleanValue()).isFalse();
        assertThat(actual.get("experimentId").textValue()).startsWith("experiment-");
        assertThat(actual.size()).isEqualTo(expected.size());
    }

    @Test
    void sameInputGivesSameExperimentIdRegardlessOfRequestId() throws Exception {
        ObjectNode first = (ObjectNode) fixture("block-request.json");
        ObjectNode second = first.deepCopy();
        second.put("requestId", "another-request");

        assertThat(experimentId(first)).isEqualTo(experimentId(second));
    }

    @Test
    void rejectsIntentDecisionMismatch() throws Exception {
        ObjectNode request = (ObjectNode) fixture("allow-request.json");
        ((ObjectNode) request.get("decision")).put("intentId", "other-intent");

        mvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content(request.toString()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"))
                .andExpect(jsonPath("$.requestId").value(request.get("requestId").textValue()));
    }

    @Test
    void rejectsUnknownField() throws Exception {
        ObjectNode request = (ObjectNode) fixture("allow-request.json");
        request.put("riskScore", 0);

        mvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content(request.toString()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("CONTRACT_VALIDATION_FAILED"));
    }

    @Test
    void rejectsInconsistentRiskPair() throws Exception {
        ObjectNode request = (ObjectNode) fixture("allow-request.json");
        ((ObjectNode) request.get("decision")).putNull("riskLevel");

        mvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content(request.toString()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("CONTRACT_VALIDATION_FAILED"));
    }

    @Test
    void unsupportedSchemaVersionIs422BeforeOtherErrors() throws Exception {
        ObjectNode request = (ObjectNode) fixture("allow-request.json");
        ((ObjectNode) request.get("decision")).put("schemaVersion", "9.9.9");
        request.remove("route");

        mvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content(request.toString()))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("UNSUPPORTED_VERSION"));
    }

    @Test
    void rejectsHeaderBodyRequestIdMismatch() throws Exception {
        JsonNode request = fixture("allow-request.json");

        mvc.perform(post(PATH).header("X-Request-ID", "different").contentType(MediaType.APPLICATION_JSON)
                        .content(request.toString()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
    }

    @Test
    void rejectsNonJsonContentType() throws Exception {
        mvc.perform(post(PATH).contentType(MediaType.TEXT_PLAIN).content("{}"))
                .andExpect(status().isUnsupportedMediaType())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
    }

    @Test
    void rejectsDuplicateJsonKeys() throws Exception {
        mvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"requestId\":\"a\",\"requestId\":\"b\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
    }

    @Test
    void unknownPathIsContract404() throws Exception {
        mvc.perform(get("/nope"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("NOT_FOUND"));
    }

    @Test
    void health() throws Exception {
        mvc.perform(get("/health")).andExpect(status().isOk()).andExpect(jsonPath("$.status").value("OK"));
    }

    private String experimentId(JsonNode request) throws Exception {
        MvcResult result = mvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON)
                .content(request.toString())).andExpect(status().isOk()).andReturn();
        return mapper.readTree(result.getResponse().getContentAsString()).get("experimentId").textValue();
    }

    private JsonNode fixture(String name) throws IOException {
        try (InputStream in = getClass().getResourceAsStream("/fixtures/gateway/" + name)) {
            return mapper.readTree(in);
        }
    }
}
