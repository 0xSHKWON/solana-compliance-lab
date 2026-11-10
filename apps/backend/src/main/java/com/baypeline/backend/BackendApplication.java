package com.baypeline.backend;

import com.baypeline.backend.support.Contract;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** Backend API & Orchestrator: Frontend와 내부 모듈을 연결하고 분석 작업의 순서·상태·결과를 관리한다. */
@SpringBootApplication
@RestController
public class BackendApplication {

    public static void main(String[] args) {
        SpringApplication.run(BackendApplication.class, args);
    }

    @GetMapping(path = "/health", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> health() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("service", "backend");
        body.put("version", "0.1.0");
        body.put("schemaVersion", Contract.SCHEMA_VERSION);
        body.put("status", "OK");
        return body;
    }
}
