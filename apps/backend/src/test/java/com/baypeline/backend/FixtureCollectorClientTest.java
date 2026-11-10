package com.baypeline.backend;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.baypeline.backend.config.BackendProperties;
import com.baypeline.backend.upstream.FixtureCollectorClient;
import com.baypeline.backend.upstream.UpstreamException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class FixtureCollectorClientTest {

    final ObjectMapper mapper = new ObjectMapper();
    final FixtureCollectorClient client = new FixtureCollectorClient(new BackendProperties(null, false, 1, 1,
            java.util.List.of(), null,
            new BackendProperties.LocalCollector(true, Path.of("src/test/resources/fixtures").toString())), mapper);

    @Test
    void returnsSnapshotWithRequestIdOfTheCall() {
        JsonNode snapshot = client.collect("r-1", request(BackendApiTest.RECIPIENT, "sanctioned", "FIXTURE"));
        assertThat(snapshot.get("requestId").textValue()).isEqualTo("r-1");
        assertThat(snapshot.get("snapshotId").textValue()).isEqualTo("sanctioned-snapshot");
    }

    @Test
    void rejectsWrongAddressLiveModeAndPathTraversal() {
        assertThatThrownBy(() -> client.collect("r", request(BackendApiTest.SENDER, "sanctioned", "FIXTURE")))
                .isInstanceOf(UpstreamException.class);
        assertThatThrownBy(() -> client.collect("r", request(BackendApiTest.RECIPIENT, "sanctioned", "LIVE")))
                .isInstanceOf(UpstreamException.class);
        assertThatThrownBy(() -> client.collect("r", request(BackendApiTest.RECIPIENT, "../sanctioned", "FIXTURE")))
                .isInstanceOf(UpstreamException.class);
    }

    private ObjectNode request(String address, String fixtureId, String mode) {
        ObjectNode request = mapper.createObjectNode();
        request.put("address", address);
        request.put("mode", mode);
        request.put("fixtureId", fixtureId);
        return request;
    }
}
