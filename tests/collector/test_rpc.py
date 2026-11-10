import json
import urllib.error

import pytest

from collector.errors import CollectionError, ProviderError
from collector.rpc import SolanaRpcClient

URL = "https://rpc.example.test/v1/secret-path-token"
KEY = "super-secret-api-key-value"


def ok(result):
    return 200, json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode()


def rpc_error(code, message="method not found"):
    return 200, json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": code, "message": message}}).encode()


class FakeTransport:
    """Replays scripted responses; an Exception item is raised instead."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, body, headers, timeout):
        self.calls.append({"url": url, "body": json.loads(body), "headers": dict(headers), "timeout": timeout})
        if not self.responses:
            raise AssertionError("unexpected extra transport call")
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def make_client(transport, sleeps=None, **kwargs):
    return SolanaRpcClient(
        URL,
        transport=transport,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
        **kwargs,
    )


def test_success_returns_result_and_sends_jsonrpc_body():
    transport = FakeTransport(ok(42))
    client = make_client(transport)

    assert client.get_slot() == 42
    call = transport.calls[0]
    assert call["url"] == URL
    assert call["body"]["jsonrpc"] == "2.0"
    assert call["body"]["method"] == "getSlot"
    assert call["body"]["params"] == [{"commitment": "finalized"}]
    assert call["headers"]["Content-Type"] == "application/json"


def test_429_then_success_retries_with_backoff():
    sleeps = []
    transport = FakeTransport((429, b"slow down"), ok(7))
    client = make_client(transport, sleeps)

    assert client.get_slot() == 7
    assert len(transport.calls) == 2
    assert sleeps == [0.5]


def test_429_exhausted_raises_rate_limited():
    sleeps = []
    transport = FakeTransport((429, b""), (429, b""), (429, b""))
    client = make_client(transport, sleeps, max_retries=2)

    with pytest.raises(ProviderError) as info:
        client.get_slot()

    error = info.value
    assert error.code == "RATE_LIMITED"
    assert error.status == 429
    assert error.retryable is True
    assert len(transport.calls) == 3
    assert sleeps == [0.5, 1.0]
    assert URL not in str(error)


def test_5xx_exhausted_raises_unavailable():
    transport = FakeTransport((503, b""), (500, b""))
    client = make_client(transport, max_retries=1)

    with pytest.raises(ProviderError) as info:
        client.get_slot()

    assert info.value.code == "UPSTREAM_UNAVAILABLE"
    assert info.value.status == 502
    assert info.value.retryable is True
    assert len(transport.calls) == 2


def test_jsonrpc_error_is_not_retried():
    transport = FakeTransport(rpc_error(-32601))
    client = make_client(transport)

    with pytest.raises(ProviderError) as info:
        client.get_slot()

    assert info.value.retryable is False
    assert str(info.value) == "Solana RPC error -32601"
    assert len(transport.calls) == 1


def test_retryable_jsonrpc_error_then_success():
    transport = FakeTransport(rpc_error(-32005, "node is behind"), ok(9))
    client = make_client(transport)

    assert client.get_slot() == 9
    assert len(transport.calls) == 2


def test_timeout_is_retried_then_succeeds():
    transport = FakeTransport(TimeoutError("timed out"), ok(5))
    client = make_client(transport)

    assert client.get_slot() == 5
    assert len(transport.calls) == 2


def test_urlerror_exhausted_raises_retryable_provider_error():
    transport = FakeTransport(
        urllib.error.URLError("connection refused"),
        TimeoutError("timed out"),
    )
    client = make_client(transport, max_retries=1)

    with pytest.raises(ProviderError) as info:
        client.get_slot()

    assert info.value.retryable is True
    assert info.value.status == 502
    assert "connection refused" not in str(info.value)


def test_api_key_sent_in_header_and_absent_from_errors():
    transport = FakeTransport((500, b""), (500, b""))
    client = make_client(transport, api_key=KEY, max_retries=1)

    with pytest.raises(ProviderError) as info:
        client.get_slot()

    assert transport.calls[0]["headers"]["X-API-KEY"] == KEY
    text = f"{info.value} {info.value!r} {info.value.args!r} {client!r}"
    assert KEY not in text
    assert URL not in text


def test_custom_api_key_header_name():
    transport = FakeTransport(ok(1))
    client = make_client(transport, api_key=KEY, api_key_header="Authorization-Token")

    client.get_slot()

    assert transport.calls[0]["headers"]["Authorization-Token"] == KEY
    assert "X-API-KEY" not in transport.calls[0]["headers"]


def test_no_api_key_header_when_unset():
    transport = FakeTransport(ok(1))
    client = make_client(transport)

    client.get_slot()

    assert "X-API-KEY" not in transport.calls[0]["headers"]


def test_from_env_missing_url_raises_503():
    with pytest.raises(CollectionError) as info:
        SolanaRpcClient.from_env({"SOLANA_RPC_API_KEY": KEY})

    assert info.value.status == 503
    assert info.value.code == "UPSTREAM_UNAVAILABLE"
    assert info.value.retryable is False
    assert KEY not in str(info.value)


def test_from_env_reads_settings():
    transport = FakeTransport(ok(3))
    client = SolanaRpcClient.from_env(
        {
            "SOLANA_RPC_URL": URL,
            "SOLANA_RPC_API_KEY": KEY,
            "SOLANA_RPC_API_KEY_HEADER": "x-token",
            "SOLANA_RPC_TIMEOUT": "2.5",
        },
        transport=transport,
        sleep=lambda s: None,
    )

    assert client.get_slot() == 3
    assert transport.calls[0]["headers"]["x-token"] == KEY
    assert transport.calls[0]["timeout"] == 2.5


def test_from_env_defaults_header_and_timeout():
    transport = FakeTransport(ok(3))
    client = SolanaRpcClient.from_env({"SOLANA_RPC_URL": URL}, transport=transport, sleep=lambda s: None)

    client.get_slot()

    assert transport.calls[0]["timeout"] == 15.0
    assert "X-API-KEY" not in transport.calls[0]["headers"]


def test_get_signatures_passes_before_and_limit():
    entries = [{"signature": "sig-a", "slot": 1, "err": None, "blockTime": 10}]
    transport = FakeTransport(ok(entries))
    client = make_client(transport)

    assert client.get_signatures_for_address("addr", before="sig-z", limit=50) == entries
    options = transport.calls[0]["body"]["params"][1]
    assert options == {"limit": 50, "commitment": "finalized", "before": "sig-z"}


def test_get_transaction_requests_jsonparsed_and_allows_null():
    transport = FakeTransport(ok(None))
    client = make_client(transport)

    assert client.get_transaction("sig-a") is None
    options = transport.calls[0]["body"]["params"][1]
    assert options["encoding"] == "jsonParsed"
    assert options["maxSupportedTransactionVersion"] == 1


def test_invalid_json_body_on_success_is_retried():
    transport = FakeTransport((200, b"<html>gateway</html>"), ok(11))
    client = make_client(transport)

    assert client.get_slot() == 11
    assert len(transport.calls) == 2


def test_default_transport_maps_http_error_to_status(monkeypatch):
    import collector.rpc as rpc_module

    def fake_urlopen(request, timeout):
        assert request.get_header("Content-type") == "application/json"
        raise urllib.error.HTTPError(URL, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(rpc_module.urllib.request, "urlopen", fake_urlopen)
    client = SolanaRpcClient(URL, max_retries=0, sleep=lambda s: None)

    with pytest.raises(ProviderError) as info:
        client.get_slot()

    assert info.value.code == "RATE_LIMITED"
