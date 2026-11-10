package com.baypeline.constellation.support;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

/** 요청 추적 ID 보관. 모든 응답의 X-Request-ID와 오류 본문의 requestId가 같은 값을 갖도록 한다. */
public final class RequestIds {

    public static final String HEADER = "X-Request-ID";
    static final String ATTRIBUTE = RequestIds.class.getName() + ".id";
    static final String HEADER_ATTRIBUTE = RequestIds.class.getName() + ".header";

    private RequestIds() {
    }

    /** 출력 가능한 ASCII 1~128자. 엔진의 X-Request-ID 규칙과 같다. */
    public static boolean valid(String value) {
        if (value == null || value.isEmpty() || value.length() > 128) {
            return false;
        }
        return value.chars().allMatch(c -> c > 32 && c < 127);
    }

    public static String current(HttpServletRequest request) {
        Object value = request.getAttribute(ATTRIBUTE);
        return value == null ? "unknown" : value.toString();
    }

    /** 클라이언트가 보낸 X-Request-ID. 없으면 null. */
    public static String fromHeader(HttpServletRequest request) {
        Object value = request.getAttribute(HEADER_ATTRIBUTE);
        return value == null ? null : value.toString();
    }

    /** Internal 요청은 본문 requestId가 기준이다. 헤더가 있으면 일치해야 한다. */
    public static void bindBody(HttpServletRequest request, HttpServletResponse response, String bodyRequestId) {
        if (!valid(bodyRequestId)) {
            throw ApiException.invalid("requestId must be printable ASCII, 1-128 characters");
        }
        String header = fromHeader(request);
        if (header != null && !header.equals(bodyRequestId)) {
            throw ApiException.invalid("Header/body requestId mismatch");
        }
        request.setAttribute(ATTRIBUTE, bodyRequestId);
        response.setHeader(HEADER, bodyRequestId);
    }
}
