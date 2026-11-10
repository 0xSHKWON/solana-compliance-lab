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

/** 기본 설정: 초안·단일 리더 모델만 등록, mock 버전과 미등록 버전은 422. */
@SpringBootTest
@AutoConfigureMockMvc
class ConstellationDefaultTest {

    @Autowired
    MockMvc mvc;

    @Autowired
    ObjectMapper mapper;

    @Test
    void unapprovedVersionIs422() throws Exception {
        JsonNode request = Fixtures.fixture(mapper, "mock-request.json");
        mvc.perform(post(Fixtures.PATH).contentType(MediaType.APPLICATION_JSON).content(request.toString()))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("UNSUPPORTED_VERSION"))
                .andExpect(jsonPath("$.requestId").value("simulation-request"));
    }

    @Test
    void structuralErrorsAre400BeforeVersionCheck() throws Exception {
        ObjectNode request = (ObjectNode) Fixtures.fixture(mapper, "mock-request.json");
        ((ObjectNode) request.get("scenario")).put("attestationPercent", 101);
        mvc.perform(post(Fixtures.PATH).contentType(MediaType.APPLICATION_JSON).content(request.toString()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("CONTRACT_VALIDATION_FAILED"));

        ((ObjectNode) request.get("scenario")).put("attestationPercent", 50);
        ((ObjectNode) request.get("scenario")).put("rejectingProposerCount", -1);
        mvc.perform(post(Fixtures.PATH).contentType(MediaType.APPLICATION_JSON).content(request.toString()))
                .andExpect(status().isBadRequest());

        ((ObjectNode) request.get("scenario")).put("rejectingProposerCount", "1");
        mvc.perform(post(Fixtures.PATH).contentType(MediaType.APPLICATION_JSON).content(request.toString()))
                .andExpect(status().isBadRequest());
    }

    @Test
    void healthListsRegisteredModels() throws Exception {
        mvc.perform(get("/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.supportedProtocolModelVersions.length()").value(2))
                .andExpect(jsonPath("$.supportedProtocolModelVersions[0]").value("0.1.0-draft"))
                .andExpect(jsonPath("$.supportedProtocolModelVersions[1]").value("0.1.0-single-leader"));
    }
}
