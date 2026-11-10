package com.baypeline.gateway.support;

import java.util.LinkedHashMap;
import java.util.Map;

/** common.schema.json#/$defs/ErrorResponse 형태: {error: {code, message, retryable}, requestId}. */
public final class ErrorBodies {

    private ErrorBodies() {
    }

    public static Map<String, Object> of(String requestId, String code, String message, boolean retryable) {
        Map<String, Object> error = new LinkedHashMap<>();
        error.put("code", code);
        error.put("message", message);
        error.put("retryable", retryable);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("error", error);
        body.put("requestId", requestId);
        return body;
    }
}
