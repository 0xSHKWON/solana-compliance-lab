"""Capture a real mainnet LIVE collection as a reproducible FIXTURE.

  SOLANA_RPC_URL=... python -m collector.capture --fixture-id real-normal-wallet \
      --address <wallet> --from 2026-10-01T00:00:00Z --to 2026-11-10T00:00:00Z --max 50 \
      --description "..."

Writes services/collector/fixtures/<id>/:
  snapshot.json            KYTDataSnapshot (mode FIXTURE, dataProvenance ON_CHAIN)
  collection-request.json  KYTCollectionRequest that loads it in FIXTURE mode
  transactions.json        every collected transaction (signature, slot, blockTime, err) for exact re-windowing
  rpc-recording.json       raw RPC results (and provider errors), so the collection can be replayed offline
  source.json              external evidence: explorer links and label dataset reference/checksum
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
from pathlib import Path

from compliance_contracts.runtime import canonical, validate

from .errors import BudgetExhausted, ProviderError
from .fixtures import DEFAULT_FIXTURE_ROOTS, REPO_ROOT
from .labels import LabelDataset, resolve_dataset_path
from .rpc import SolanaRpcClient
from .service import Collector

EXPLORER = "https://explorer.solana.com"


def _key(method, args, kwargs):
    return canonical({"method": method, "args": list(args), "kwargs": kwargs})


class RecordingRpc:
    """Wraps an RPC client and records every data call with its result or provider error."""

    def __init__(self, inner):
        self._inner, self.calls = inner, []
        self._lock = threading.Lock()

    def bind_deadline(self, deadline):
        # Timing control, not data: forwarded but never recorded (it differs on every run).
        bind = getattr(self._inner, "bind_deadline", None)
        if callable(bind):
            bind(deadline)

    def __getattr__(self, method):
        target = getattr(self._inner, method)

        def call(*args, **kwargs):
            record = {"method": method, "args": list(args), "kwargs": kwargs}
            try:
                result = target(*args, **kwargs)
            except ProviderError as error:
                record["error"] = {"message": str(error), "code": error.code, "status": error.status,
                                   "retryable": error.retryable, "budget": isinstance(error, BudgetExhausted)}
                with self._lock:
                    self.calls.append(record)
                raise
            record["result"] = result
            with self._lock:
                self.calls.append(record)
            return result
        return call


class ReplayRpc:
    """Serves calls recorded by RecordingRpc; an unrecorded call is a provider error."""

    def __init__(self, calls):
        self._calls = {_key(c["method"], c["args"], c["kwargs"]): c for c in calls}

    def bind_deadline(self, deadline):
        pass  # replay is instantaneous

    def __getattr__(self, method):
        def call(*args, **kwargs):
            record = self._calls.get(_key(method, args, kwargs))
            if record is None:
                raise ProviderError(f"Unrecorded RPC call: {method}", retryable=False)
            error = record.get("error")
            if error is not None:
                if error.get("budget"):
                    raise BudgetExhausted(error["message"])
                raise ProviderError(error["message"], retryable=error["retryable"], status=error["status"],
                                    code=error["code"])
            return record["result"]
        return call


def _write(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    return resolved.relative_to(REPO_ROOT).as_posix() if resolved.is_relative_to(REPO_ROOT) else resolved.name


def capture(fixture_id, address, from_time, to_time, max_transactions, description, output_root=None, rpc=None,
            provider=None, clock=None, label_path=None):
    provider = provider or os.environ.get("SOLANA_RPC_PROVIDER") or "SOLANA_RPC"
    recorder = RecordingRpc(rpc or SolanaRpcClient.from_env())
    dataset_path = resolve_dataset_path(label_path)
    labels = LabelDataset.load(dataset_path)
    request_id = f"{fixture_id}-request"
    scope = {"fromTime": from_time, "toTime": to_time, "maxTransactions": max_transactions}
    collector = Collector(rpc_factory=lambda: recorder, label_loader=lambda: labels, provider_name=provider,
                          clock=clock)
    live, result = collector.collect_detailed({"requestId": request_id, "address": address,
                                               "network": "mainnet-beta", "mode": "LIVE", "scope": scope})
    snapshot = {**live, "mode": "FIXTURE",
                "dataProvenance": {"dataType": "ON_CHAIN", "source": provider,
                                   "reference": f"{EXPLORER}/address/{address}"}}
    request = {"requestId": request_id, "address": address, "network": "mainnet-beta", "mode": "FIXTURE",
               "fixtureId": fixture_id, "scope": scope}
    validate("collector", "KYTDataSnapshot", snapshot)
    validate("collector", "KYTCollectionRequest", request)
    source = {
        "fixtureId": fixture_id,
        "dataType": "ON_CHAIN",
        "description": description,
        "capturedAt": live["collectedAt"],
        "provider": provider,
        "liveSnapshotId": live["snapshotId"],
        "address": {"address": address, "explorer": f"{EXPLORER}/address/{address}"},
        "tokenAccountsScanned": list(result.token_accounts),
        "transactions": [{"signature": row["signature"], "failed": row["err"] is not None,
                          "explorer": f"{EXPLORER}/tx/{row['signature']}"} for row in result.signatures],
        "labelDataset": {**live["labelDataset"],
                         "reference": labels.reference(),
                         "file": _display_path(dataset_path),
                         "sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
                         "matchedReferenceIds": sorted({label["referenceId"] for label in live["labels"]})},
        "notes": "Transaction data is real mainnet data. Labels come only from the dataset named above; "
                 "a risk signal is not a legal finding.",
    }
    directory = Path(output_root or DEFAULT_FIXTURE_ROOTS[0]) / fixture_id
    directory.mkdir(parents=True, exist_ok=True)
    _write(directory / "snapshot.json", snapshot)
    _write(directory / "collection-request.json", request)
    _write(directory / "transactions.json", {"transactions": result.signatures})
    # Calls run concurrently; sort them so the recording is byte-for-byte reproducible.
    calls = sorted(recorder.calls, key=lambda c: _key(c["method"], c["args"], c["kwargs"]))
    _write(directory / "rpc-recording.json", {"collectedAt": live["collectedAt"], "calls": calls})
    _write(directory / "source.json", source)
    return directory, snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description="Capture a LIVE collection as a FIXTURE")
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--from", dest="from_time", required=True)
    parser.add_argument("--to", dest="to_time", required=True)
    parser.add_argument("--max", dest="max_transactions", type=int, default=100)
    parser.add_argument("--description", required=True)
    parser.add_argument("--output-root")
    parser.add_argument("--labels", dest="label_path", help="Label dataset file (default: COLLECTOR_LABEL_DATASET)")
    args = parser.parse_args(argv)
    directory, snapshot = capture(args.fixture_id, args.address, args.from_time, args.to_time,
                                  args.max_transactions, args.description, args.output_root,
                                  label_path=args.label_path)
    coverage = snapshot["coverage"]
    print(f"{directory}: {coverage['status']} {coverage['reasons']} "
          f"tx={coverage['transactionCount']} transfers={coverage['transferCount']} labels={len(snapshot['labels'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
