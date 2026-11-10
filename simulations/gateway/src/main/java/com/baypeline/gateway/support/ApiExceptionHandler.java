package com.baypeline.gateway.support;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpMediaTypeNotAcceptableException;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.NoHandlerFoundException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

/** 모든 실패를 HTTP 상태 + {error, requestId}로 응답한다. 내부 예외 내용은 노출하지 않는다. */
@RestControllerAdvice
public class ApiExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(ApiExceptionHandler.class);

    @ExceptionHandler(ApiException.class)
    ResponseEntity<Map<String, Object>> api(ApiException e, HttpServletRequest request) {
        return respond(request, e.status(), e.code(), e.getMessage(), e.retryable());
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    ResponseEntity<Map<String, Object>> unreadable(HttpServletRequest request) {
        return respond(request, HttpStatus.BAD_REQUEST, "INVALID_REQUEST", "Invalid JSON", false);
    }

    @ExceptionHandler(HttpMediaTypeNotSupportedException.class)
    ResponseEntity<Map<String, Object>> mediaType(HttpServletRequest request) {
        return respond(request, HttpStatus.UNSUPPORTED_MEDIA_TYPE, "INVALID_REQUEST",
                "Content-Type must be application/json", false);
    }

    @ExceptionHandler(HttpMediaTypeNotAcceptableException.class)
    ResponseEntity<Map<String, Object>> notAcceptable(HttpServletRequest request) {
        return respond(request, HttpStatus.NOT_ACCEPTABLE, "INVALID_REQUEST", "Only application/json is produced",
                false);
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    ResponseEntity<Map<String, Object>> method(HttpServletRequest request) {
        return respond(request, HttpStatus.METHOD_NOT_ALLOWED, "INVALID_REQUEST", "Unsupported HTTP method", false);
    }

    @ExceptionHandler({MissingServletRequestParameterException.class, MethodArgumentTypeMismatchException.class})
    ResponseEntity<Map<String, Object>> parameter(HttpServletRequest request) {
        return respond(request, HttpStatus.BAD_REQUEST, "INVALID_REQUEST", "Invalid request parameter", false);
    }

    @ExceptionHandler({NoResourceFoundException.class, NoHandlerFoundException.class})
    ResponseEntity<Map<String, Object>> notFound(HttpServletRequest request) {
        return respond(request, HttpStatus.NOT_FOUND, "NOT_FOUND", "Unknown endpoint", false);
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<Map<String, Object>> unexpected(Exception e, HttpServletRequest request) {
        log.error("Unhandled error (requestId={})", RequestIds.current(request), e);
        return respond(request, HttpStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Internal error", false);
    }

    private ResponseEntity<Map<String, Object>> respond(HttpServletRequest request, HttpStatus status, String code,
            String message, boolean retryable) {
        String requestId = RequestIds.current(request);
        return ResponseEntity.status(status)
                .header(RequestIds.HEADER, requestId)
                .body(ErrorBodies.of(requestId, code, message, retryable));
    }
}
