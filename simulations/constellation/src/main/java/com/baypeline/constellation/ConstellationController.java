package com.baypeline.constellation;

import com.baypeline.constellation.support.Contract;
import com.baypeline.constellation.support.RequestIds;
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
public class ConstellationController {

    private final ConstellationSimulator simulator;

    public ConstellationController(ConstellationSimulator simulator) {
        this.simulator = simulator;
    }

    @PostMapping(path = "/internal/v1/constellation/simulate",
            consumes = MediaType.APPLICATION_JSON_VALUE, produces = MediaType.APPLICATION_JSON_VALUE)
    public ObjectNode simulate(@RequestBody JsonNode body, HttpServletRequest request, HttpServletResponse response) {
        if (body != null && body.isObject() && body.has("requestId") && body.get("requestId").isTextual()) {
            RequestIds.bindBody(request, response, body.get("requestId").textValue());
        }
        return simulator.simulate(body);
    }

    @GetMapping(path = "/health", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> health() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("service", "constellation-simulator");
        body.put("version", "0.1.0");
        body.put("schemaVersion", Contract.SCHEMA_VERSION);
        body.put("status", "OK");
        body.put("supportedProtocolModelVersions", simulator.supportedVersions());
        return body;
    }
}
