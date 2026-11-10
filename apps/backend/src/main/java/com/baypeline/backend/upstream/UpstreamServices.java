package com.baypeline.backend.upstream;

import com.baypeline.backend.config.BackendProperties;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.stereotype.Component;

/** Backend가 호출하는 내부 모듈 목록. 각 모듈의 Internal API 경로는 contracts/openapi.yaml 을 따른다. */
@Component
public class UpstreamServices {

    private final CollectorClient collector;
    private final InternalClient client;
    private final BackendProperties.Upstream urls;

    public UpstreamServices(CollectorClient collector, InternalClient client, BackendProperties properties) {
        this.collector = collector;
        this.client = client;
        this.urls = properties.upstream();
    }

    public JsonNode collect(String requestId, ObjectNode request) {
        return collector.collect(requestId, request);
    }

    public JsonNode evaluateKyt(String requestId, ObjectNode request) {
        return client.post("kyt-engine", urls.kytUrl(), "/internal/v1/kyt/evaluate", requestId, request);
    }

    public JsonNode decidePolicy(String requestId, ObjectNode request) {
        return client.post("policy-engine", urls.policyUrl(), "/internal/v1/policy/decide", requestId, request);
    }

    public JsonNode runGateway(String requestId, ObjectNode request) {
        return client.post("mock-gateway", urls.gatewayUrl(), "/internal/v1/gateway/experiment", requestId,
                request);
    }

    public JsonNode simulateConstellation(String requestId, ObjectNode request) {
        return client.post("constellation-simulator", urls.constellationUrl(), "/internal/v1/constellation/simulate",
                requestId, request);
    }
}
