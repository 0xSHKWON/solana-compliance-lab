package com.baypeline.gateway.support;

import org.springframework.http.HttpStatus;

/** 계약의 ErrorResponse로 변환되는 예외. code는 common.schema.json의 ErrorCode 값을 사용한다. */
public class ApiException extends RuntimeException {

    private final HttpStatus status;
    private final String code;
    private final boolean retryable;

    public ApiException(HttpStatus status, String code, String message, boolean retryable) {
        super(message);
        this.status = status;
        this.code = code;
        this.retryable = retryable;
    }

    public static ApiException contract(String message) {
        return new ApiException(HttpStatus.BAD_REQUEST, "CONTRACT_VALIDATION_FAILED", message, false);
    }

    public static ApiException invalid(String message) {
        return new ApiException(HttpStatus.BAD_REQUEST, "INVALID_REQUEST", message, false);
    }

    public static ApiException unsupportedVersion(String message) {
        return new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "UNSUPPORTED_VERSION", message, false);
    }

    public HttpStatus status() {
        return status;
    }

    public String code() {
        return code;
    }

    public boolean retryable() {
        return retryable;
    }
}
