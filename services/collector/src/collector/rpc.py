"""Minimal Solana JSON-RPC client built on urllib (stdlib only).

Secrets (RPC URL, API key) never appear in exception messages or ``repr``.
"""
from __future__ import annotations

import http.client
import itertools
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Mapping

from .errors import BudgetExhausted, CollectionError, ProviderError

DEFAULT_API_KEY_HEADER = "X-API-KEY"
DEFAULT_TIMEOUT = 15.0
BACKOFF_BASE_SECONDS = 0.5
# JSON-RPC error codes that indicate a transient node/provider condition.
RETRYABLE_RPC_CODES = frozenset({-32005, -32429, -32603})
RATE_LIMIT_RPC_CODE = -32429

Transport = Callable[[str, bytes, dict, float], "tuple[int, bytes]"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects: urllib would replay custom headers (the API key) to the new location."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _urllib_transport(url: str, body: bytes, headers: dict, timeout: float) -> tuple[int, bytes]:
    """POST ``body`` and return ``(status, body)``. HTTP errors (including 3xx) are returned, not raised.

    urllib honors HTTPS_PROXY / HTTP_PROXY from the environment by default.
    Network failures (URLError, TimeoutError, OSError, HTTPException) propagate to the retry loop.
    """
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        try:
            payload = exc.read()
        except (OSError, http.client.HTTPException):
            payload = b""
        return exc.code, payload


def _valid_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return parsed.scheme in ("https", "http") and bool(parsed.netloc)


def _decode(raw: bytes | str) -> object | None:
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


# Mainnet carries v1 transactions; a lower value makes the RPC reject them with -32015.
DEFAULT_MAX_TRANSACTION_VERSION = 1


class SolanaRpcClient:
    """JSON-RPC 2.0 client with retry/backoff for Solana nodes and providers."""

    def __init__(
        self,
        url: str,
        api_key: str | None = None,
        api_key_header: str = DEFAULT_API_KEY_HEADER,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = 3,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_transaction_version: int = DEFAULT_MAX_TRANSACTION_VERSION,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(url, str) or not _valid_url(url):
            raise CollectionError("LIVE mode is not configured", "UPSTREAM_UNAVAILABLE", 503, False)
        if not (isinstance(timeout, (int, float)) and math.isfinite(timeout) and timeout > 0):
            raise CollectionError("LIVE mode is not configured", "UPSTREAM_UNAVAILABLE", 503, False)
        if int(max_transaction_version) < 0:
            raise CollectionError("LIVE mode is not configured", "UPSTREAM_UNAVAILABLE", 503, False)
        self._url = url
        self._api_key = api_key or None
        self._api_key_header = api_key_header or DEFAULT_API_KEY_HEADER
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self._transport = transport or _urllib_transport
        self._sleep = sleep
        self._ids = itertools.count(1)
        self.max_transaction_version = int(max_transaction_version)
        self._clock = clock
        self._deadline: float | None = None

    def bind_deadline(self, deadline: float | None) -> None:
        """Bound every later call (attempts, backoff, timeouts) by ``deadline`` on this client's clock."""
        self._deadline = deadline

    def _remaining(self) -> float:
        if self._deadline is None:
            return math.inf
        return self._deadline - self._clock()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(url=<redacted>, api_key={'set' if self._api_key else 'unset'})"

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ, **kwargs) -> "SolanaRpcClient":
        url = env.get("SOLANA_RPC_URL")
        if not url:
            raise CollectionError("LIVE mode is not configured", "UPSTREAM_UNAVAILABLE", 503, False)
        try:
            timeout = float(env.get("SOLANA_RPC_TIMEOUT") or DEFAULT_TIMEOUT)
            max_version = int(env.get("SOLANA_RPC_MAX_TX_VERSION") or DEFAULT_MAX_TRANSACTION_VERSION)
        except ValueError:
            raise CollectionError("LIVE mode is not configured", "UPSTREAM_UNAVAILABLE", 503, False) from None
        return cls(
            url,
            api_key=env.get("SOLANA_RPC_API_KEY") or None,
            api_key_header=env.get("SOLANA_RPC_API_KEY_HEADER") or DEFAULT_API_KEY_HEADER,
            timeout=timeout,
            max_transaction_version=max_version,
            **kwargs,
        )

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            headers[self._api_key_header] = self._api_key
        return headers

    def call(self, method: str, params: list | None = None):
        """Call a JSON-RPC method and return its ``result``. Retries transient failures."""
        body = json.dumps(
            {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or []},
            separators=(",", ":"),
        ).encode("utf-8")
        headers = self._headers()
        last_error: ProviderError | None = None

        for attempt in range(self.max_retries + 1):
            if attempt:
                backoff = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                if self._remaining() <= backoff:
                    raise BudgetExhausted()
                self._sleep(backoff)
            remaining = self._remaining()
            if remaining <= 0:
                raise BudgetExhausted()
            try:
                status, raw = self._transport(self._url, body, headers, min(self.timeout, remaining))
            except (OSError, http.client.HTTPException, ValueError):  # TimeoutError, URLError, IncompleteRead, ...
                # Never chain the original exception: urllib messages can contain the URL.
                last_error = ProviderError("Solana RPC unavailable", retryable=True, status=502)
                continue

            if status == 429:
                last_error = ProviderError("Solana RPC rate limited", retryable=True, status=429, code="RATE_LIMITED")
                continue
            if status >= 500:
                last_error = ProviderError("Solana RPC unavailable", retryable=True, status=502)
                continue

            payload = _decode(raw)
            if payload is None:
                if 200 <= status < 300:
                    last_error = ProviderError("Solana RPC returned an invalid response", retryable=True, status=502)
                    continue
                raise ProviderError(f"Solana RPC rejected request (HTTP {status})", retryable=False, status=502)
            if not isinstance(payload, dict):
                raise ProviderError("Solana RPC returned an invalid response", retryable=False, status=502)

            error = payload.get("error")
            if error is not None:
                code = error.get("code") if isinstance(error, dict) else None
                if not isinstance(code, int) or isinstance(code, bool):
                    code = None
                if code in RETRYABLE_RPC_CODES:
                    if code == RATE_LIMIT_RPC_CODE:
                        last_error = ProviderError("Solana RPC rate limited", retryable=True, status=429, code="RATE_LIMITED")
                    else:
                        last_error = ProviderError("Solana RPC unavailable", retryable=True, status=502)
                    continue
                raise ProviderError(f"Solana RPC error {code}", retryable=False, status=502)

            if "result" not in payload:
                raise ProviderError("Solana RPC returned an invalid response", retryable=False, status=502)
            return payload["result"]

        if last_error is None:
            raise BudgetExhausted()
        raise last_error

    def get_slot(self, commitment: str = "finalized") -> int:
        result = self.call("getSlot", [{"commitment": commitment}])
        if not isinstance(result, int) or isinstance(result, bool):
            raise ProviderError("Solana RPC returned an invalid slot", retryable=False, status=502)
        return result

    def get_signatures_for_address(
        self,
        address: str,
        before: str | None = None,
        limit: int = 1000,
        commitment: str = "finalized",
    ) -> list[dict]:
        options: dict = {"limit": limit, "commitment": commitment}
        if before is not None:
            options["before"] = before
        result = self.call("getSignaturesForAddress", [address, options])
        if not isinstance(result, list):
            raise ProviderError("Solana RPC returned an invalid signature list", retryable=False, status=502)
        return result

    def get_token_accounts_by_owner(self, owner: str, program_id: str, commitment: str = "finalized") -> list[str]:
        """Addresses of the token accounts ``owner`` currently holds under one token program."""
        result = self.call(
            "getTokenAccountsByOwner",
            [owner, {"programId": program_id},
             {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}, "commitment": commitment}],
        )
        value = result.get("value") if isinstance(result, dict) else None
        if not isinstance(value, list) or not all(isinstance(item, dict) and isinstance(item.get("pubkey"), str)
                                                  for item in value):
            raise ProviderError("Solana RPC returned an invalid token account list", retryable=False, status=502)
        return [item["pubkey"] for item in value]

    def get_transaction(self, signature: str, commitment: str = "finalized") -> dict | None:
        result = self.call(
            "getTransaction",
            [
                signature,
                {
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": self.max_transaction_version,
                    "commitment": commitment,
                },
            ],
        )
        if result is not None and not isinstance(result, dict):
            raise ProviderError("Solana RPC returned an invalid transaction", retryable=False, status=502)
        return result
