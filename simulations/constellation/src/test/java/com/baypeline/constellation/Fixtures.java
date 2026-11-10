package com.baypeline.constellation;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.io.InputStream;

final class Fixtures {

    static final String PATH = "/internal/v1/constellation/simulate";

    private Fixtures() {
    }

    static JsonNode fixture(ObjectMapper mapper, String name) throws IOException {
        try (InputStream in = Fixtures.class
                .getResourceAsStream("/fixtures/constellation/" + name)) {
            return mapper.readTree(in);
        }
    }

}
