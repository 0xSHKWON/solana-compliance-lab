"""Collection orchestration: request validation, LIVE/FIXTURE dispatch and snapshot assembly."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from compliance_contracts.runtime import ContractViolation, instant, stable_id, validate

from .errors import CollectionError, ProviderError
from .fixtures import FixtureStore, apply_request
from .labels import LabelDataset
from .live import LiveSource
from .normalizer import normalize_transaction
from .rpc import SolanaRpcClient

SCHEMA_VERSION = "0.1.0"
NETWORK = "mainnet-beta"
DEFAULT_MAX_TRANSACTIONS = 1000
_ADDRESS_KEYS = ("fromAddress", "toAddress", "sourceAccount", "destinationAccount")


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _transfer_order(transfer):
    inner = -1 if transfer["innerInstructionIndex"] is None else transfer["innerInstructionIndex"]
    return (transfer["slot"], transfer["signature"], transfer["instructionIndex"], inner, transfer["transferOrdinal"])


class Collector:
    """POST /internal/v1/collect operation. Stateless per request; no background monitoring."""

    def __init__(self, fixtures=None, rpc_factory=None, label_loader=None, max_transactions=None,
                 provider_name=None, clock=None, env=None, live_options=None):
        env = os.environ if env is None else env
        self._env = env
        self._fixtures = fixtures if fixtures is not None else FixtureStore()
        self._rpc_factory = rpc_factory or (lambda: SolanaRpcClient.from_env(env))
        self._label_loader = label_loader or (lambda: LabelDataset.load(env.get("COLLECTOR_LABEL_DATASET") or None))
        self._max_transactions = int(max_transactions or env.get("COLLECTOR_MAX_TRANSACTIONS") or DEFAULT_MAX_TRANSACTIONS)
        self._provider = provider_name or env.get("SOLANA_RPC_PROVIDER") or "SOLANA_RPC"
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._live_options = {
            "fetch_workers": int(env.get("COLLECTOR_FETCH_WORKERS") or 16),
            # Must stay below the Backend's upstream read timeout (30s by default).
            "time_budget": float(env.get("COLLECTOR_TIME_BUDGET_SECONDS") or 20),
            "max_token_accounts": int(env.get("COLLECTOR_MAX_TOKEN_ACCOUNTS") or 100),
            **(live_options or {}),
        }

    def collect(self, request):
        validate("collector", "KYTCollectionRequest", request)
        scope = request["scope"]
        if scope["maxTransactions"] > self._max_transactions:
            raise ContractViolation(f"maxTransactions exceeds collector limit {self._max_transactions}", "INVALID_REQUEST")
        if request["mode"] == "FIXTURE":
            snapshot = apply_request(self._fixtures.load(request["fixtureId"]), request)
        else:
            snapshot = self._collect_live(request)
        self._check_output(request, snapshot)
        return snapshot

    def _collect_live(self, request):
        address, scope = request["address"], request["scope"]
        from_time, to_time = instant(scope["fromTime"]), instant(scope["toTime"])
        if from_time > self._clock():
            raise ContractViolation("Scope starts in the future", "INVALID_REQUEST")
        labels = self._label_loader()  # fail before touching the provider if label metadata is missing
        result = LiveSource(self._rpc_factory(), **self._live_options).fetch(
            address, from_time, to_time, scope["maxTransactions"])
        reasons = set(result.reasons)
        transfers = {}
        for transaction in result.transactions:
            try:
                normalized = normalize_transaction(transaction, address, result.token_accounts)
            except ProviderError:
                # One structurally broken transaction must not discard the rest of the snapshot.
                reasons.add("PARSE_FAILED")
                continue
            reasons |= set(normalized.reasons)
            for transfer in normalized.transfers:
                transfers.setdefault(transfer["id"], transfer)
        rows = sorted(transfers.values(), key=_transfer_order)
        related = {address} | {row[key] for row in rows for key in _ADDRESS_KEYS if row[key] is not None}
        status = "PARTIAL" if reasons else "COMPLETE"
        coverage = {
            "status": status,
            "reasons": sorted(reasons),
            "fromTime": scope["fromTime"],
            "toTime": scope["toTime"],
            "snapshotSlot": result.snapshot_slot,
            "transactionCount": result.transaction_count,
            "transferCount": len(rows),
            "reachedTimeBoundary": status == "COMPLETE" or bool(result.reached_time_boundary),
        }
        snapshot_id = stable_id("snapshot", {
            "requestId": request["requestId"], "address": address, "scope": scope,
            "snapshotSlot": result.snapshot_slot, "transferIds": [row["id"] for row in rows],
        })
        return {
            "schemaVersion": SCHEMA_VERSION,
            "snapshotId": snapshot_id,
            "requestId": request["requestId"],
            "address": address,
            "network": NETWORK,
            "mode": "LIVE",
            "transfers": rows,
            "labels": labels.labels_for(sorted(related), NETWORK),
            "labelDataset": labels.metadata(),
            "coverage": coverage,
            "collectedAt": _utc(self._clock()),
            # The provider URL may embed an API key, so it is never recorded as a reference.
            "dataProvenance": {"dataType": "ON_CHAIN", "source": self._provider, "reference": None},
        }

    @staticmethod
    def _check_output(request, snapshot):
        validate("collector", "KYTDataSnapshot", snapshot)
        for key in ("requestId", "address", "network", "mode"):
            if snapshot[key] != request[key]:
                raise CollectionError(f"Snapshot {key} does not match request", "INTERNAL_ERROR", 500)
        coverage = snapshot["coverage"]
        if coverage["transactionCount"] > request["scope"]["maxTransactions"]:
            raise CollectionError("Snapshot exceeds requested transaction limit", "INTERNAL_ERROR", 500)
        if (coverage["fromTime"], coverage["toTime"]) != (request["scope"]["fromTime"], request["scope"]["toTime"]):
            raise CollectionError("Snapshot time scope does not match request", "INTERNAL_ERROR", 500)
