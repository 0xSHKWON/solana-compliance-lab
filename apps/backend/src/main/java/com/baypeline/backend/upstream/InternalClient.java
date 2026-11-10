package com.baypeline.backend.upstream;

import com.baypeline.backend.config.BackendProperties;
import com.baypeline.backend.support.RequestIds;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import org.springframework.http.MediaType;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;

/**
 * Internal API 호출용 JSON 클라이언트. 본문 requestId와 X-Request-ID 헤더를 같은 값으로 보낸다.
 * 엔진 HTTP 서버는 chunked 전송을 거부하므로 Content-Length를 명시한다.
 */
@Component
public class InternalClient {

    private final RestClient rest;
    private final ObjectMapper mapper;

    public InternalClient(RestClient.Builder builder, BackendProperties properties, ObjectMapper mapper) {
        HttpClient http = HttpClient.newBuilder()
                .connectTimeout(properties.upstream().connectTimeout())
                .version(HttpClient.Version.HTTP_1_1)
                .build();
        JdkClientHttpRequestFactory factory = new JdkClientHttpRequestFactory(http);
        factory.setReadTimeout(properties.upstream().readTimeout());
        this.rest = builder.requestFactory(factory).build();
        this.mapper = mapper;
    }

    public JsonNode post(String service, String baseUrl, String path, String requestId, JsonNode body) {
        byte[] payload = body.toString().getBytes(StandardCharsets.UTF_8);
        try {
            return rest.post()
                    .uri(stripSlash(baseUrl) + path)
                    .contentType(MediaType.APPLICATION_JSON)
                    .accept(MediaType.APPLICATION_JSON)
                    .contentLength(payload.length)
                    .header(RequestIds.HEADER, requestId)
                    .body(payload)
                    .exchange((request, response) -> {
                        int status = response.getStatusCode().value();
                        byte[] raw = response.getBody().readAllBytes();
                        JsonNode node;
                        try {
                            node = mapper.readTree(raw);
                        } catch (IOException e) {
                            throw UpstreamException.invalidResponse(service, "body is not JSON");
                        }
                        if (status == 200) {
                            if (node == null || !node.isObject()) {
                                throw UpstreamException.invalidResponse(service, "body is not a JSON object");
                            }
                            return node;
                        }
                        JsonNode error = node == null ? null : node.path("error");
                        String code = error == null ? "UPSTREAM_UNAVAILABLE" : error.path("code").asText("");
                        String message = error == null ? "" : error.path("message").asText("");
                        boolean retryable = error != null && error.path("retryable").asBoolean(status >= 500);
                        throw new UpstreamException(service, status, code,
                                message.isEmpty() ? "HTTP " + status : message, retryable);
                    });
        } catch (ResourceAccessException e) {
            throw UpstreamException.unavailable(service);
        }
    }

    private static String stripSlash(String url) {
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }
}
