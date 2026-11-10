package com.baypeline.gateway;

import com.baypeline.gateway.support.Contract;
import com.baypeline.gateway.support.RequestIds;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class GatewayController {

    private final GatewayEngine engine;

    public GatewayController(GatewayEngine engine) {
        this.engine = engine;
    }

    @PostMapping(path = "/internal/v1/gateway/experiment",
            consumes = MediaType.APPLICATION_JSON_VALUE, produces = MediaType.APPLICATION_JSON_VALUE)
    public ObjectNode experiment(@RequestBody JsonNode body, HttpServletRequest request,
            HttpServletResponse response) {
        if (body != null && body.isObject() && body.has("requestId") && body.get("requestId").isTextual()) {
            RequestIds.bindBody(request, response, body.get("requestId").textValue());
        }
        return engine.experiment(body);
    }

    @GetMapping(path = "/health", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> health() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("service", "mock-gateway");
        body.put("version", "0.1.0");
        body.put("schemaVersion", Contract.SCHEMA_VERSION);
        body.put("status", "OK");
        return body;
    }
}
