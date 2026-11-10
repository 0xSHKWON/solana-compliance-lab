"""Collector HTTP transport: POST /internal/v1/collect over a real local server."""
import json
import threading
from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path

import pytest

from collector.errors import CollectionError
from collector.service import Collector
from compliance_contracts.runtime import validate
from engine_common.http import make_server

COLLECT = "/internal/v1/collect"
CONTRACT_REQUEST = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "normal" / "collection-request.json"


@contextmanager
def running(operation):
    server = make_server("collector", "0.1.0", COLLECT, operation)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def call(port, path, body=None, method="POST"):
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    payload = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
    try:
        connection.request(method, path, body=payload, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), json.loads(response.read())
    finally:
        connection.close()


@pytest.fixture
def collector_port(monkeypatch):
    for name in ("COLLECTOR_FIXTURE_ROOTS", "COLLECTOR_MAX_TRANSACTIONS", "COLLECTOR_LABEL_DATASET"):
        monkeypatch.delenv(name, raising=False)
    with running(Collector().collect) as port:
        yield port


def test_fixture_request_over_http_returns_validated_snapshot(collector_port):
    request = json.loads(CONTRACT_REQUEST.read_text(encoding="utf-8"))

    status, headers, body = call(collector_port, COLLECT, request)

    assert status == 200
    assert headers["X-Request-ID"] == request["requestId"]
    assert body["requestId"] == request["requestId"]
    validate("collector", "KYTDataSnapshot", body)


def test_unknown_fixture_over_http_is_not_found(collector_port):
    request = json.loads(CONTRACT_REQUEST.read_text(encoding="utf-8"))
    request["fixtureId"] = "no-such-fixture"

    status, headers, body = call(collector_port, COLLECT, request)

    assert status == 404
    validate("common", "ErrorResponse", body)
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["retryable"] is False
    assert body["requestId"] == headers["X-Request-ID"] == request["requestId"]


def test_retryable_collection_error_is_reported_in_body():
    def unavailable(request):
        raise CollectionError("Upstream temporarily unavailable", "UPSTREAM_UNAVAILABLE", 503, retryable=True)

    with running(unavailable) as port:
        status, _, body = call(port, COLLECT, {"requestId": "retry-test"})

    assert status == 503
    validate("common", "ErrorResponse", body)
    assert body["error"]["retryable"] is True
    assert body["error"]["code"] == "UPSTREAM_UNAVAILABLE"


def test_health_endpoint_reports_collector(collector_port):
    status, _, body = call(collector_port, "/health", method="GET")

    assert status == 200
    assert body["service"] == "collector"
    assert body["status"] == "OK"
