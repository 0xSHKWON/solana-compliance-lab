package com.baypeline.backend.analysis;

import com.baypeline.backend.support.RequestIds;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping(path = "/api/v1/analyses", produces = MediaType.APPLICATION_JSON_VALUE)
public class AnalysisController {

    private final AnalysisService service;

    public AnalysisController(AnalysisService service) {
        this.service = service;
    }

    @PostMapping(consumes = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<ObjectNode> create(@RequestBody JsonNode body, HttpServletRequest request) {
        ObjectNode accepted = service.create(body, RequestIds.current(request));
        return ResponseEntity.accepted()
                .location(URI.create("/api/v1/analyses/" + accepted.get("analysisId").textValue()))
                .body(accepted);
    }

    @GetMapping("/{id}")
    public ObjectNode get(@PathVariable String id) {
        return service.get(id);
    }

    @GetMapping("/{id}/transfers")
    public ObjectNode transfers(@PathVariable String id, @RequestParam(required = false) String limit,
            @RequestParam(required = false) String cursor) {
        return service.transfers(id, limit, cursor);
    }
}
