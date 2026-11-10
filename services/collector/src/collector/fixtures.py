"""Fixture manager: stored snapshots re-windowed to a collection request (FIXTURE mode)."""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

from compliance_contracts.runtime import instant, stable_id

from .errors import CollectionError, FixtureNotFound

REPO_ROOT = Path(__file__).resolve().parents[4]
# Real mainnet captures take precedence over synthetic fixtures with the same id.
DEFAULT_FIXTURE_ROOTS = (
    REPO_ROOT / "services" / "collector" / "fixtures",
    REPO_ROOT / "contracts" / "fixtures",
)
ROOTS_ENV = "COLLECTOR_FIXTURE_ROOTS"
SNAPSHOT_FILE = "snapshot.json"

_FIXTURE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_ADDRESS_KEYS = ("fromAddress", "toAddress", "sourceAccount", "destinationAccount")
_LIMIT = "TRANSACTION_LIMIT_REACHED"
_BOUNDARY = "TIME_BOUNDARY_NOT_REACHED"
_OWNER = "OWNER_UNRESOLVED"
_TIMESTAMP = "TIMESTAMP_UNAVAILABLE"


def default_roots() -> list[Path]:
    configured = os.environ.get(ROOTS_ENV)
    if configured:
        return [Path(part) for part in configured.split(os.pathsep) if part]
    return list(DEFAULT_FIXTURE_ROOTS)


def _is_fixture_id(value) -> bool:
    return isinstance(value, str) and _FIXTURE_ID.fullmatch(value) is not None


class FixtureStore:
    def __init__(self, roots=None):
        self._roots = [Path(root) for root in (default_roots() if roots is None else roots)]

    def _locate(self, fixture_id: str) -> Path | None:
        """First root (in order) holding a snapshot for the id, provided it resolves inside that root."""
        for root in self._roots:
            path = root / fixture_id / SNAPSHOT_FILE
            if not path.is_file():
                continue
            if not path.resolve().is_relative_to(root.resolve()):
                continue
            return path
        return None

    @staticmethod
    def _read(path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            raise CollectionError("Fixture snapshot is unreadable", "INTERNAL_ERROR", 500, False) from None
        if not isinstance(data, dict):
            raise CollectionError("Fixture snapshot is unreadable", "INTERNAL_ERROR", 500, False)
        return data

    def list(self) -> list[dict]:
        names = set()
        for root in self._roots:
            if root.is_dir():
                names.update(child.name for child in root.iterdir() if _is_fixture_id(child.name))
        result = []
        for name in sorted(names):
            path = self._locate(name)
            if path is None:
                continue
            snapshot = self._read(path)
            result.append({
                "fixtureId": name,
                "address": snapshot["address"],
                "dataType": snapshot["dataProvenance"]["dataType"],
                "path": str(path),
            })
        return result

    def load(self, fixture_id: str) -> dict:
        if not _is_fixture_id(fixture_id):
            raise FixtureNotFound()
        path = self._locate(fixture_id)
        if path is None:
            raise FixtureNotFound()
        return copy.deepcopy(self._read(path))


def apply_request(snapshot: dict, request: dict) -> dict:
    """Return the stored snapshot adapted to the request scope; the inputs are never modified."""
    if request["address"] != snapshot["address"]:
        raise CollectionError("Fixture address mismatch", "CONFLICT", 409, False)
    scope, coverage = request["scope"], snapshot["coverage"]
    max_transactions = scope["maxTransactions"]
    same_window = (instant(coverage["fromTime"]), instant(coverage["toTime"])) == (
        instant(scope["fromTime"]), instant(scope["toTime"]))
    if same_window and coverage["transactionCount"] <= max_transactions:
        result = copy.deepcopy(snapshot)
        result["requestId"] = request["requestId"]
        result["mode"] = "FIXTURE"
        return result

    from_time, to_time = instant(scope["fromTime"]), instant(scope["toTime"])
    fixture_from, fixture_to = instant(coverage["fromTime"]), instant(coverage["toTime"])
    window_inside = from_time >= fixture_from and to_time <= fixture_to
    window_covers = from_time <= fixture_from and to_time >= fixture_to

    kept = []
    for transfer in snapshot["transfers"]:
        if transfer["timestamp"] is None:
            # An unknown timestamp can only be placed inside a window that covers the whole fixture.
            if window_covers:
                kept.append(transfer)
        elif from_time <= instant(transfer["timestamp"]) < to_time:
            kept.append(transfer)

    slots = {}
    for transfer in kept:
        slots.setdefault(transfer["signature"], transfer["slot"])
    limit_hit = len(slots) > max_transactions
    if limit_hit:
        newest = sorted(slots, key=lambda sig: (-slots[sig], sig))[:max_transactions]
        keep = set(newest)
        kept = [transfer for transfer in kept if transfer["signature"] in keep]

    reasons = {r for r in coverage["reasons"] if r not in (_OWNER, _TIMESTAMP)}
    if any(not transfer["ownerResolved"] for transfer in kept):
        reasons.add(_OWNER)
    # A dropped unknown-timestamp transfer may still fall inside the narrower window, so completeness stays unproven.
    unknown_time_outside = any(t["timestamp"] is None for t in snapshot["transfers"]) and not window_covers
    if any(transfer["timestamp"] is None for transfer in kept) or unknown_time_outside:
        reasons.add(_TIMESTAMP)
    if not window_inside:
        reasons.add(_BOUNDARY)
    if limit_hit:
        reasons.add(_LIMIT)
    reached = bool(coverage["reachedTimeBoundary"]) and window_inside and not limit_hit

    related = {snapshot["address"]} | {t[key] for t in kept for key in _ADDRESS_KEYS if t[key] is not None}
    result = copy.deepcopy(snapshot)
    result.update({
        "snapshotId": stable_id("snapshot", {"fixtureSnapshotId": snapshot["snapshotId"], "scope": scope}),
        "requestId": request["requestId"],
        "mode": "FIXTURE",
        "transfers": copy.deepcopy(kept),
        "labels": [copy.deepcopy(label) for label in snapshot["labels"] if label["address"] in related],
        "coverage": {
            "status": "PARTIAL" if reasons else "COMPLETE",
            "reasons": sorted(reasons),
            "fromTime": scope["fromTime"],
            "toTime": scope["toTime"],
            "snapshotSlot": coverage["snapshotSlot"],
            "transactionCount": len({t["signature"] for t in kept}),
            "transferCount": len(kept),
            "reachedTimeBoundary": reached,
        },
    })
    return result
