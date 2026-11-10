package com.baypeline.backend.experiment;

import com.baypeline.backend.support.RequestIds;
import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping(path = "/api/v1/experiments", consumes = MediaType.APPLICATION_JSON_VALUE,
        produces = MediaType.APPLICATION_JSON_VALUE)
public class ExperimentController {

    private final ExperimentService service;

    public ExperimentController(ExperimentService service) {
        this.service = service;
    }

    @PostMapping("/gateway")
    public JsonNode gateway(@RequestBody JsonNode body, HttpServletRequest request) {
        return service.gateway(body, RequestIds.current(request));
    }

    @PostMapping("/constellation")
    public JsonNode constellation(@RequestBody JsonNode body, HttpServletRequest request) {
        return service.constellation(body, RequestIds.current(request));
    }
}
