package com.baypeline.backend.upstream;

import com.baypeline.backend.support.ApiException;
import java.util.Set;
import org.springframework.http.HttpStatus;

/** 내부 모듈(Collector·KYT·Policy·Gateway·Simulator) 호출 실패. */
public class UpstreamException extends RuntimeException {

    private static final Set<String> CODES = Set.of("INVALID_REQUEST", "CONTRACT_VALIDATION_FAILED", "NOT_FOUND",
            "CONFLICT", "ANALYSIS_NOT_READY", "ASSESSMENT_MISMATCH", "UNSUPPORTED_VERSION", "UPSTREAM_UNAVAILABLE",
            "RATE_LIMITED", "INTERNAL_ERROR");

    private final String service;
    private final int status;
    private final String code;
    private final boolean retryable;

    public UpstreamException(String service, int status, String code, String message, boolean retryable) {
        super(message);
        this.service = service;
        this.status = status;
        this.code = CODES.contains(code) ? code : "UPSTREAM_UNAVAILABLE";
        this.retryable = retryable;
    }

    public static UpstreamException unavailable(String service) {
        return new UpstreamException(service, 503, "UPSTREAM_UNAVAILABLE", service + " is unavailable", true);
    }

    public static UpstreamException invalidResponse(String service, String detail) {
        return new UpstreamException(service, 502, "UPSTREAM_UNAVAILABLE",
                service + " returned an invalid response: " + detail, false);
    }

    /**
     * Public 응답으로 변환한다. 버전 미지원(422)·충돌(409)·과부하(429)·연결 불가(503)는 의미를 유지하고,
     * 그 외 내부 모듈 오류는 Backend가 만든 요청 문제이거나 내부 장애이므로 502로 감싼다.
     */
    public ApiException toPublic() {
        return switch (status) {
            case 409, 422 -> new ApiException(HttpStatus.valueOf(status), code, publicMessage(), retryable);
            case 429 -> new ApiException(HttpStatus.TOO_MANY_REQUESTS, "RATE_LIMITED", publicMessage(), true);
            case 503 -> new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "UPSTREAM_UNAVAILABLE", publicMessage(),
                    true);
            default -> new ApiException(HttpStatus.BAD_GATEWAY, "UPSTREAM_UNAVAILABLE", publicMessage(), retryable);
        };
    }

    /** 분석 작업 FAILED 상태에 저장할 오류 코드. */
    public String jobErrorCode() {
        return switch (status) {
            case 409, 422, 429 -> code;
            default -> "UPSTREAM_UNAVAILABLE";
        };
    }

    public String publicMessage() {
        String message = getMessage() == null ? "error" : getMessage();
        if (message.length() > 300) {
            message = message.substring(0, 300);
        }
        return message.startsWith(service) ? message : service + ": " + message;
    }

    public String service() {
        return service;
    }

    public int status() {
        return status;
    }

    public String code() {
        return code;
    }

    public boolean retryable() {
        return retryable;
    }
}
