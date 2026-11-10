package com.baypeline.backend.compliance;

import com.baypeline.backend.support.RequestIds;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ComplianceController {

    private final ComplianceService service;

    public ComplianceController(ComplianceService service) {
        this.service = service;
    }

    @PostMapping(path = "/api/v1/compliance/evaluate", consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.APPLICATION_JSON_VALUE)
    public ObjectNode evaluate(@RequestBody JsonNode body, HttpServletRequest request) {
        return service.evaluate(body, RequestIds.current(request));
    }
}
