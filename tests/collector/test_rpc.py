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

    class FakeOpener:
        def open(self, request, timeout):
            assert request.get_header("Content-type") == "application/json"
            raise urllib.error.HTTPError(URL, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(rpc_module, "_OPENER", FakeOpener())
    client = SolanaRpcClient(URL, max_retries=0, sleep=lambda s: None)

    with pytest.raises(ProviderError) as info:
        client.get_slot()

    assert info.value.code == "RATE_LIMITED"


def test_get_token_accounts_by_owner_returns_pubkeys_only():
    transport = FakeTransport(ok({"context": {"slot": 1}, "value": [{"pubkey": "ata-1", "account": {}}, {"pubkey": "ata-2"}]}))
    client = make_client(transport)

    assert client.get_token_accounts_by_owner("wallet", "program") == ["ata-1", "ata-2"]
    body = transport.calls[0]["body"]
    assert body["method"] == "getTokenAccountsByOwner"
    assert body["params"][0] == "wallet" and body["params"][1] == {"programId": "program"}
    assert body["params"][2]["dataSlice"] == {"offset": 0, "length": 0}  # account data is not needed


def test_get_token_accounts_by_owner_rejects_malformed_result():
    client = make_client(FakeTransport(ok({"value": [{"no": "pubkey"}]})))
    with pytest.raises(ProviderError):
        client.get_token_accounts_by_owner("wallet", "program")



# --- security / robustness regressions ---------------------------------------------------------

def test_redirect_is_not_followed_and_api_key_is_not_forwarded():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    received = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.headers.get("X-API-KEY"))
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"jsonrpc":"2.0","id":1,"result":1}')
        do_POST = do_GET

        def log_message(self, *args):
            pass

    target = HTTPServer(("127.0.0.1", 0), Target)

    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/")
            self.end_headers()

        def log_message(self, *args):
            pass

    redirect = HTTPServer(("127.0.0.1", 0), Redirect)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (target, redirect)]
    for thread in threads:
        thread.start()
    try:
        client = SolanaRpcClient(f"http://127.0.0.1:{redirect.server_port}/", api_key="SECRET-KEY",
                                 max_retries=0, sleep=lambda s: None)
        with pytest.raises(ProviderError) as info:
            client.get_slot()
    finally:
        for server in (target, redirect):
            server.shutdown(); server.server_close()

    assert received == []  # the key never reached the redirect target
    assert "SECRET-KEY" not in str(info.value)


@pytest.mark.parametrize("url", ["solana-mainnet.example?api-key=SECRET", "ftp://host/SECRET", "https://", ""])
def test_malformed_url_is_rejected_without_echoing_it(url):
    with pytest.raises(CollectionError) as info:
        SolanaRpcClient.from_env({"SOLANA_RPC_URL": url}) if url else SolanaRpcClient(url)
    assert info.value.status == 503 and "SECRET" not in str(info.value)


@pytest.mark.parametrize("timeout", ["nan", "-1", "inf", "0"])
def test_invalid_timeout_is_rejected(timeout):
    with pytest.raises(CollectionError):
        SolanaRpcClient.from_env({"SOLANA_RPC_URL": URL, "SOLANA_RPC_TIMEOUT": timeout})


def test_incomplete_read_is_retried_as_provider_failure():
    import http.client

    def transport(url, body, headers, timeout):
        raise http.client.IncompleteRead(b"partial", 100)

    client = SolanaRpcClient(URL, max_retries=1, transport=transport, sleep=lambda s: None)
    with pytest.raises(ProviderError) as info:
        client.get_slot()
    assert info.value.retryable is True


def test_non_integer_rpc_error_code_does_not_crash():
    client = make_client(FakeTransport((200, json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": []}}).encode())))
    with pytest.raises(ProviderError) as info:
        client.get_slot()
    assert info.value.retryable is False


def test_deadline_bounds_attempt_timeout_and_stops_retries():
    from collector.errors import BudgetExhausted

    now = [0.0]
    timeouts = []

    def transport(url, body, headers, timeout):
        timeouts.append(timeout)
        now[0] += timeout  # the attempt uses its whole timeout
        raise TimeoutError()

    client = SolanaRpcClient(URL, timeout=15.0, max_retries=3, transport=transport,
                             sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    client.bind_deadline(4.0)

    with pytest.raises(BudgetExhausted):
        client.get_slot()
    assert timeouts == [4.0]  # bounded by the remaining budget, then no retry past the deadline
    assert now[0] <= 4.0


def test_retention_methods_validate_results():
    assert make_client(FakeTransport(ok(461886947))).get_first_available_block() == 461886947
    assert make_client(FakeTransport(ok(None))).get_block_time(1) is None
    with pytest.raises(ProviderError):
        make_client(FakeTransport(ok("x"))).get_block_time(1)


def test_non_retryable_rpc_error_keeps_the_rpc_code():
    client = make_client(FakeTransport((200, json.dumps(
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32012, "message": "scan aborted"}}).encode())))
    with pytest.raises(ProviderError) as info:
        client.get_slot()
    assert info.value.rpc_code == -32012
