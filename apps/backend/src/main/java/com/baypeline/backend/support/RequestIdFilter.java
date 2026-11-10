package com.baypeline.backend.support;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Collections;
import java.util.List;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/** X-Request-ID 검증·발급과 본문 크기 제한. 필터 단계 오류도 계약 ErrorResponse로 응답한다. */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class RequestIdFilter extends OncePerRequestFilter {

    private final ObjectMapper mapper;
    private final long maxBodyBytes;

    public RequestIdFilter(ObjectMapper mapper, @Value("${compliance.max-body-bytes:1048576}") long maxBodyBytes) {
        this.mapper = mapper;
        this.maxBodyBytes = maxBodyBytes;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String generated = UUID.randomUUID().toString();
        request.setAttribute(RequestIds.ATTRIBUTE, generated);
        response.setHeader(RequestIds.HEADER, generated);

        List<String> headers = Collections.list(request.getHeaders(RequestIds.HEADER));
        if (headers.size() > 1 || (headers.size() == 1 && !RequestIds.valid(headers.get(0)))) {
            write(response, generated, HttpStatus.BAD_REQUEST, "INVALID_REQUEST", "Invalid X-Request-ID");
            return;
        }
        if (headers.size() == 1) {
            String id = headers.get(0);
            request.setAttribute(RequestIds.ATTRIBUTE, id);
            request.setAttribute(RequestIds.HEADER_ATTRIBUTE, id);
            response.setHeader(RequestIds.HEADER, id);
        }
        if (request.getContentLengthLong() > maxBodyBytes) {
            write(response, RequestIds.current(request), HttpStatus.PAYLOAD_TOO_LARGE, "INVALID_REQUEST",
                    "Request body too large");
            return;
        }
        chain.doFilter(request, response);
    }

    private void write(HttpServletResponse response, String requestId, HttpStatus status, String code, String message)
            throws IOException {
        response.setStatus(status.value());
        response.setContentType("application/json;charset=UTF-8");
        mapper.writeValue(response.getOutputStream(), ErrorBodies.of(requestId, code, message, false));
    }
}
