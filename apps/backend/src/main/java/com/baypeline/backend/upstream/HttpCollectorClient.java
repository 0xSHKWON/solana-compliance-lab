package com.baypeline.backend.upstream;

import com.baypeline.backend.config.BackendProperties;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/** 실제 Collector 서비스(POST /internal/v1/collect) 호출. 기본 구현. */
@Component
@ConditionalOnProperty(name = "compliance.local-collector.enabled", havingValue = "false", matchIfMissing = true)
public class HttpCollectorClient implements CollectorClient {

    private final InternalClient client;
    private final BackendProperties properties;

    public HttpCollectorClient(InternalClient client, BackendProperties properties) {
        this.client = client;
        this.properties = properties;
    }

    @Override
    public JsonNode collect(String requestId, ObjectNode collectionRequest) {
        return client.post("collector", properties.upstream().collectorUrl(), "/internal/v1/collect", requestId,
                collectionRequest);
    }
}
