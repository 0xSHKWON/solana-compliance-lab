from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.client import HTTPConnection
import json
import threading

import pytest

from compliance_contracts.runtime import validate
from engine_common.http import make_server
from kyt_engine import Detector
from policy_engine import PolicyEngine

KYT = "/internal/v1/kyt/evaluate"
POLICY = "/internal/v1/policy/decide"


@contextmanager
def running(service, path, operation, **kwargs):
    server = make_server(service, "1.0.0", path, operation, **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.fixture(scope="module")
def ports():
    with running("kyt-engine", KYT, Detector().evaluate) as kyt_port:
        with running("policy-engine", POLICY, PolicyEngine().decide) as policy_port:
            yield {KYT: kyt_port, POLICY: policy_port}


def call(port, path, body=None, headers=None, method="POST"):
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    payload = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
    merged = {"Content-Type": "application/json", **(headers or {})}
    try:
        connection.request(method, path, body=payload, headers=merged)
        response = connection.getresponse()
        status, response_headers, data = response.status, dict(response.getheaders()), response.read()
        return status, response_headers, json.loads(data)
    finally:
        connection.close()


@pytest.mark.parametrize("scenario", ["normal", "sanctioned", "direct-flow", "warn", "repeat", "partial", "partial-sanctioned", "spl", "token-2022"])
def test_real_http_chain_produces_gateway_ready_decisions(ports, fixture_json, scenario):
    status, headers, evaluation = call(ports[KYT], KYT, fixture_json(scenario + "/evaluation-request.json"))
    assert status == 200
    assert evaluation == fixture_json(scenario + "/evaluation.json")
    request = fixture_json(scenario + "/policy-request.json")
    request["assessments"]["recipient"] = evaluation
    status, headers, decision = call(ports[POLICY], POLICY, request)
    assert status == 200
    assert headers["X-Request-ID"] == request["requestId"]
    assert decision == fixture_json(scenario + "/decision.json")
    validate("experiment", "GatewayExperimentRequest", {
        "requestId": "gateway-integration", "intent": request["intent"], "decision": decision,
        "route": {"routeId": "our-service", "policyEnforced": True, "warningAcknowledged": False},
    })


@pytest.mark.parametrize("body,headers,expected", [
    (b"{", {}, 400), (b"\xff", {}, 400),
    (b'{"requestId":"first","requestId":"second"}', {}, 400),
    (b'{"requestId":NaN}', {}, 400),
    ([], {}, 400), (b"{}", {"Content-Type": "text/plain"}, 415),
    (b"{}", {"Content-Type": "application/json; charset=latin1"}, 415),
    (b"{}", {"Content-Length": str(9*1024*1024)}, 413),
    (b"{}", {"Transfer-Encoding": "chunked"}, 400),
])
def test_transport_errors_are_structured(ports, body, headers, expected):
    status, response_headers, result = call(ports[KYT], KYT, body, headers)
    assert status == expected
    validate("common", "ErrorResponse", result)
    assert result["requestId"] == response_headers["X-Request-ID"]


def test_correlation_header_must_match_body(ports, fixture_json):
    request = fixture_json("normal/evaluation-request.json")
    status, headers, result = call(ports[KYT], KYT, request, {"X-Request-ID": "different"})
    assert status == 400
    assert result["requestId"] == "different"


def test_body_request_id_cannot_inject_response_headers(ports, fixture_json):
    request = fixture_json("normal/evaluation-request.json")
    request["requestId"] = "unsafe\r\nInjected: true"
    status, headers, result = call(ports[KYT], KYT, request)
    assert status == 400 and "Injected" not in headers
    assert "\r" not in result["requestId"] and "\n" not in result["requestId"]


def test_unicode_source_roundtrips_and_invalid_surrogates_are_rejected(ports, fixture_json):
    request = fixture_json("sanctioned/evaluation-request.json")
    request["snapshot"]["dataProvenance"]["source"] = "테스트 출처 🐈"
    status, _, result = call(ports[KYT], KYT, request)
    assert status == 200
    assert result["evidences"][0]["source"]["dataProvenance"]["source"] == "테스트 출처 🐈"
    request["snapshot"]["dataProvenance"]["source"] = "\ud800"
    assert call(ports[KYT], KYT, request)[0] == 400


@pytest.mark.parametrize("path", [KYT, POLICY])
def test_unknown_versions_are_422(ports, fixture_json, path):
    request = fixture_json("normal/" + ("evaluation-request.json" if path == KYT else "policy-request.json"))
    request["rulesetVersion" if path == KYT else "policyVersion"] = "99.0.0"
    status, _, result = call(ports[path], path, request)
    assert status == 422 and result["error"]["code"] == "UNSUPPORTED_VERSION"


def test_deeply_nested_input_is_a_request_error(ports):
    value = {}
    for _ in range(100):
        value = {"nested": value}
    status, _, _ = call(ports[KYT], KYT, value)
    assert status == 400


def test_health_and_unknown_route(ports):
    assert call(ports[KYT], "/health", method="GET")[2]["service"] == "kyt-engine"
    status, _, body = call(ports[KYT], "/not-a-route", {})
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


def test_internal_failure_does_not_expose_exception():
    def broken(request):
        raise RuntimeError("private-provider-key")
    with running("test", KYT, broken) as port:
        status, _, body = call(port, KYT, {"requestId": "test"})
        assert status == 500
        assert "private-provider-key" not in json.dumps(body)


def test_concurrent_requests_remain_deterministic(ports, fixture_json):
    request = fixture_json("warn/evaluation-request.json")
    expected = fixture_json("warn/evaluation.json")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: call(ports[KYT], KYT, request), range(24)))
    assert all(status == 200 and body == expected for status, _, body in results)
