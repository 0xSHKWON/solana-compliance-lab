"""Capture a real mainnet LIVE collection as a reproducible FIXTURE.

  SOLANA_RPC_URL=... python -m collector.capture --fixture-id real-normal-wallet \
      --address <wallet> --from 2026-10-01T00:00:00Z --to 2026-11-10T00:00:00Z --max 50 \
      --description "..."

Writes services/collector/fixtures/<id>/:
  snapshot.json            KYTDataSnapshot (mode FIXTURE, dataProvenance ON_CHAIN)
  collection-request.json  KYTCollectionRequest that loads it in FIXTURE mode
  rpc-recording.json       raw RPC results, so the normalization can be replayed offline
  source.json              external evidence: explorer links and label dataset reference
"""
from __future__ import annotations

import argparse
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from compliance_contracts.runtime import canonical, validate

from .fixtures import DEFAULT_FIXTURE_ROOTS
from .rpc import SolanaRpcClient
from .service import Collector

EXPLORER = "https://explorer.solana.com"
OFAC_SEARCH = "https://sanctionssearch.ofac.treas.gov/"


def _key(method, args, kwargs):
    return canonical({"method": method, "args": list(args), "kwargs": kwargs})


class RecordingRpc:
    """Wraps an RPC client and records every high-level call and its result."""

    def __init__(self, inner):
        self._inner, self.calls = inner, []
        self._lock = threading.Lock()

    def __getattr__(self, method):
        target = getattr(self._inner, method)

        def call(*args, **kwargs):
            result = target(*args, **kwargs)
            with self._lock:
                self.calls.append({"method": method, "args": list(args), "kwargs": kwargs, "result": result})
            return result
        return call


class ReplayRpc:
    """Serves results recorded by RecordingRpc; any unrecorded call is an error."""

    def __init__(self, calls):
        self._results = {_key(c["method"], c["args"], c["kwargs"]): c["result"] for c in calls}

    def __getattr__(self, method):
        def call(*args, **kwargs):
            key = _key(method, args, kwargs)
            if key not in self._results:
                raise KeyError(f"Unrecorded RPC call: {method}")
            return self._results[key]
        return call


def _write(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def capture(fixture_id, address, from_time, to_time, max_transactions, description, output_root=None, rpc=None,
            provider="NODIT_SOLANA_RPC", clock=None):
    recorder = RecordingRpc(rpc or SolanaRpcClient.from_env())
    request_id = f"{fixture_id}-request"
    scope = {"fromTime": from_time, "toTime": to_time, "maxTransactions": max_transactions}
    collector = Collector(rpc_factory=lambda: recorder, provider_name=provider, clock=clock)
    live = collector.collect({"requestId": request_id, "address": address, "network": "mainnet-beta",
                              "mode": "LIVE", "scope": scope})
    snapshot = {**live, "mode": "FIXTURE",
                "dataProvenance": {"dataType": "ON_CHAIN", "source": provider,
                                   "reference": f"{EXPLORER}/address/{address}"}}
    request = {"requestId": request_id, "address": address, "network": "mainnet-beta", "mode": "FIXTURE",
               "fixtureId": fixture_id, "scope": scope}
    validate("collector", "KYTDataSnapshot", snapshot)
    validate("collector", "KYTCollectionRequest", request)
    signatures = sorted({c["args"][0] for c in recorder.calls if c["method"] == "get_transaction"})
    source = {
        "fixtureId": fixture_id,
        "dataType": "ON_CHAIN",
        "description": description,
        "capturedAt": live["collectedAt"],
        "provider": provider,
        "liveSnapshotId": live["snapshotId"],
        "address": {"address": address, "explorer": f"{EXPLORER}/address/{address}"},
        "transactions": [{"signature": s, "explorer": f"{EXPLORER}/tx/{s}"} for s in signatures],
        "labelDataset": {**live["labelDataset"],
                         "reference": OFAC_SEARCH if live["labelDataset"]["source"] == "OFAC_SDN" else None,
                         "matchedReferenceIds": sorted({l["referenceId"] for l in live["labels"]})},
        "notes": "Transaction data is real mainnet data. Labels come only from the dataset named above; "
                 "a risk signal is not a legal finding.",
    }
    directory = Path(output_root or DEFAULT_FIXTURE_ROOTS[0]) / fixture_id
    directory.mkdir(parents=True, exist_ok=True)
    _write(directory / "snapshot.json", snapshot)
    _write(directory / "collection-request.json", request)
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
    args = parser.parse_args(argv)
    directory, snapshot = capture(args.fixture_id, args.address, args.from_time, args.to_time,
                                  args.max_transactions, args.description, args.output_root)
    coverage = snapshot["coverage"]
    print(f"{directory}: {coverage['status']} {coverage['reasons']} "
          f"tx={coverage['transactionCount']} transfers={coverage['transferCount']} labels={len(snapshot['labels'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
