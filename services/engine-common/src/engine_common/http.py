"""Bounded JSON-only HTTP transport for independently runnable PoC engines."""
import json
import logging
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

from compliance_contracts.runtime import ContractViolation, validate

LOGGER = logging.getLogger(__name__)


def _correlation(value):
    return isinstance(value, str) and 0 < len(value) <= 128 and all(32 < ord(c) < 127 for c in value)


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def _invalid_constant(value):
    raise ValueError("Invalid JSON numeric constant")


def decode_json(raw):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ContractViolation("Invalid JSON", "INVALID_REQUEST") from None


def make_server(service, version, path, operation, host="127.0.0.1", port=0, max_body_bytes=8 * 1024 * 1024):
    if max_body_bytes < 1:
        raise ValueError("max_body_bytes must be positive")

    class Handler(BaseHTTPRequestHandler):
        server_version = "ComplianceEngine/1.0"

        def setup(self):
            super().setup()
            self.connection.settimeout(10)
            self.request_id = str(uuid4())

        def log_message(self, format, *args):
            # No body, address, provider URL, or raw request ID in transport logs.
            pass

        def _reply(self, status, value):
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("X-Request-ID", self.request_id)
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            if self.command != "HEAD":
                self.wfile.write(encoded)

        def _error(self, status, code, message, retryable=False):
            result = {"error": {"code": code, "message": message, "retryable": retryable}, "requestId": self.request_id}
            validate("common", "ErrorResponse", result)
            self._reply(status, result)

        def send_error(self, code, message=None, explain=None):
            self._error(code, "INVALID_REQUEST", "Unsupported HTTP request")

        def _header_id(self):
            headers = self.headers.get_all("X-Request-ID", [])
            if len(headers) > 1 or (headers and not _correlation(headers[0])):
                raise ContractViolation("Invalid X-Request-ID", "INVALID_REQUEST")
            if headers:
                self.request_id = headers[0]
            return headers[0] if headers else None

        def do_GET(self):
            try:
                self._header_id()
                if self.path != "/health":
                    self._error(404, "NOT_FOUND", "Unknown endpoint")
                    return
                self._reply(200, {"service": service, "version": version, "schemaVersion": "0.1.0", "status": "OK"})
            except ContractViolation as error:
                self._error(error.status, error.code, str(error))

        def do_POST(self):
            try:
                header_id = self._header_id()
                if self.path != path:
                    self._error(404, "NOT_FOUND", "Unknown endpoint")
                    return
                if self.headers.get_content_type() != "application/json" or self.headers.get("Content-Type") is None:
                    raise ContractViolation("Content-Type must be application/json", "INVALID_REQUEST", 415)
                charset = self.headers.get_content_charset("utf-8")
                if charset.lower() not in {"utf-8", "utf8"}:
                    raise ContractViolation("JSON must use UTF-8", "INVALID_REQUEST", 415)
                lengths = self.headers.get_all("Content-Length", [])
                if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                    raise ContractViolation("One Content-Length is required; chunked encoding is unsupported", "INVALID_REQUEST")
                digits = lengths[0].lstrip("0") or "0"
                if len(digits) > len(str(max_body_bytes)):
                    raise ContractViolation("Request body too large", "INVALID_REQUEST", 413)
                length = int(digits)
                if length > max_body_bytes:
                    raise ContractViolation("Request body too large", "INVALID_REQUEST", 413)
                if length == 0:
                    raise ContractViolation("Empty request body", "INVALID_REQUEST")
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ContractViolation("Incomplete request body", "INVALID_REQUEST")
                request = decode_json(body)
                if isinstance(request, dict) and "requestId" in request:
                    if not _correlation(request["requestId"]):
                        raise ContractViolation("requestId must be printable ASCII, 1-128 characters", "INVALID_REQUEST")
                    if header_id is not None and request["requestId"] != header_id:
                        raise ContractViolation("Header/body requestId mismatch", "INVALID_REQUEST")
                    self.request_id = request["requestId"]
                self._reply(200, operation(request))
            except ContractViolation as error:
                self._error(error.status, error.code, str(error), getattr(error, "retryable", False))
            except (TimeoutError, socket.timeout):
                self._error(400, "INVALID_REQUEST", "Request body timed out")
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except Exception:
                LOGGER.exception("Engine execution failed")
                self._error(500, "INTERNAL_ERROR", "Engine execution failed")

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
