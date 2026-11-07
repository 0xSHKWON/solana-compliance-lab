"""CLI with local-file/stdin evaluation or a standalone HTTP process."""
import argparse
import json
import sys
from pathlib import Path

from compliance_contracts.runtime import ContractViolation
from .http import decode_json, make_server


def run(service, version, path, factory, method, default_port):
    for stream in [sys.stdout, sys.stderr]:
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=service)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=default_port, type=int)
    parser.add_argument("--max-body-bytes", default=8 * 1024 * 1024, type=int)
    parser.add_argument("--input", help="Evaluate a JSON file, or '-' for stdin, then exit")
    args = parser.parse_args()
    operation = getattr(factory(), method)
    if args.input is not None:
        try:
            raw = sys.stdin.buffer.read() if args.input == "-" else Path(args.input).read_bytes()
            request = decode_json(raw)
            result = operation(request)
        except (ContractViolation, ValueError, OSError) as error:
            print(json.dumps({"error": {"code": getattr(error, "code", "INVALID_REQUEST"), "message": str(error), "retryable": False},
                              "requestId": request.get("requestId", "cli") if "request" in locals() and isinstance(request, dict) else "cli"}), file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        return 0
    with make_server(service, version, path, operation, args.host, args.port, args.max_body_bytes) as server:
        print(f"{service} {version} http://{args.host}:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
