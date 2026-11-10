package com.baypeline.backend.upstream;

import com.baypeline.backend.config.BackendProperties;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.regex.Pattern;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/**
 * 로컬 개발 전용 Collector 대체 구현. Collector 서비스(권상현 담당)가 준비되기 전에도
 * Backend → KYT → Policy 흐름을 띄워볼 수 있도록 contracts/fixtures/{fixtureId}/snapshot.json 을 반환한다.
 *
 * <p>정규화·위험도 계산은 하지 않는다. Collector와 같이 응답 requestId만 요청 값으로 채운다.
 * FIXTURE 모드만 지원하며, 요청 주소가 fixture의 address와 다르면 오류를 반환한다.
 */
@Component
@ConditionalOnProperty(name = "compliance.local-collector.enabled", havingValue = "true")
public class FixtureCollectorClient implements CollectorClient {

    private static final Pattern SAFE_ID = Pattern.compile("^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$");

    private final Path fixturesDir;
    private final ObjectMapper mapper;

    public FixtureCollectorClient(BackendProperties properties, ObjectMapper mapper) {
        this.fixturesDir = Path.of(properties.localCollector().fixturesDir()).toAbsolutePath().normalize();
        this.mapper = mapper;
    }

    @Override
    public JsonNode collect(String requestId, ObjectNode request) {
        if (!"FIXTURE".equals(request.path("mode").asText())) {
            throw new UpstreamException("collector", 400, "INVALID_REQUEST",
                    "local fixture collector supports FIXTURE mode only", false);
        }
        String fixtureId = request.path("fixtureId").asText();
        if (!SAFE_ID.matcher(fixtureId).matches()) {
            throw new UpstreamException("collector", 404, "NOT_FOUND", "fixture not found", false);
        }
        Path file = fixturesDir.resolve(fixtureId).resolve("snapshot.json").normalize();
        if (!file.startsWith(fixturesDir) || !Files.isRegularFile(file)) {
            throw new UpstreamException("collector", 404, "NOT_FOUND", "fixture not found: " + fixtureId, false);
        }
        ObjectNode snapshot;
        try {
            snapshot = (ObjectNode) mapper.readTree(file.toFile());
        } catch (IOException | ClassCastException e) {
            throw UpstreamException.invalidResponse("collector", "fixture is not a JSON object");
        }
        if (!snapshot.path("address").asText().equals(request.path("address").asText())) {
            throw new UpstreamException("collector", 400, "INVALID_REQUEST",
                    "fixture " + fixtureId + " is for address " + snapshot.path("address").asText(), false);
        }
        snapshot.put("requestId", requestId);
        return snapshot;
    }
}
