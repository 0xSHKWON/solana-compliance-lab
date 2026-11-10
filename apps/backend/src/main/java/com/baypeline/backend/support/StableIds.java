package com.baypeline.backend.support;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Iterator;
import java.util.Map;
import java.util.TreeMap;

/**
 * prefix-sha256(정렬된 키의 압축 JSON). contracts/runtime.py 의 stable_id 와 같은 방식으로,
 * 같은 의미의 입력은 실행 시각·requestId와 무관하게 같은 ID를 만든다.
 */
public final class StableIds {

    private static final ObjectMapper CANONICAL = JsonMapper.builder()
            .enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS)
            .build();

    private StableIds() {
    }

    public static String of(String prefix, JsonNode value) {
        try {
            byte[] canonical = CANONICAL.writeValueAsString(sorted(value)).getBytes(StandardCharsets.UTF_8);
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(canonical);
            return prefix + "-" + HexFormat.of().formatHex(digest);
        } catch (JsonProcessingException | NoSuchAlgorithmException e) {
            throw new IllegalStateException("Cannot build stable id", e);
        }
    }

    private static Object sorted(JsonNode node) {
        if (node instanceof ObjectNode object) {
            Map<String, Object> map = new TreeMap<>();
            for (Iterator<Map.Entry<String, JsonNode>> it = object.fields(); it.hasNext(); ) {
                Map.Entry<String, JsonNode> entry = it.next();
                map.put(entry.getKey(), sorted(entry.getValue()));
            }
            return map;
        }
        if (node.isArray()) {
            java.util.List<Object> list = new java.util.ArrayList<>();
            node.forEach(item -> list.add(sorted(item)));
            return list;
        }
        return node;
    }
}
