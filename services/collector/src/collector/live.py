"""Live transaction collection for one address over a half-open UTC window ``[from, to)``."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from compliance_contracts.runtime import require

from .errors import ProviderError

REASON_LIMIT = "TRANSACTION_LIMIT_REACHED"
REASON_FETCH_FAILED = "TRANSACTION_FETCH_FAILED"
REASON_BOUNDARY = "TIME_BOUNDARY_NOT_REACHED"
FINALIZED = "finalized"


@dataclass
class LiveResult:
    transactions: list[dict]
    failed_count: int
    transaction_count: int
    reasons: set[str] = field(default_factory=set)
    reached_time_boundary: bool = False
    snapshot_slot: int = 0


def _utc(value: datetime, name: str) -> datetime:
    require(
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None,
        f"{name} must be a timezone-aware datetime",
    )
    return value.astimezone(timezone.utc)


class LiveSource:
    def __init__(self, rpc, page_size: int = 1000, max_pages: int = 50) -> None:
        require(page_size >= 1, "page_size must be positive")
        require(max_pages >= 1, "max_pages must be positive")
        self._rpc = rpc
        self._page_size = page_size
        # Bounds the signature scan for very busy wallets whose window lies far in the past.
        self._max_pages = max_pages

    def fetch(self, address: str, from_time: datetime, to_time: datetime, max_transactions: int) -> LiveResult:
        start = _utc(from_time, "from_time")
        end = _utc(to_time, "to_time")
        require(start < end, "Empty or inverted time range")
        require(max_transactions >= 1, "max_transactions must be positive")

        from_ts = start.timestamp()
        to_ts = end.timestamp()
        snapshot_slot = self._rpc.get_slot(commitment=FINALIZED)

        seen: set[str] = set()
        transactions: list[dict] = []
        reasons: set[str] = set()
        failed_count = 0
        transaction_count = 0
        reached_boundary = False
        limit_hit = False
        before: str | None = None
        pages = 0

        while pages < self._max_pages:
            pages += 1
            page = self._rpc.get_signatures_for_address(
                address, before=before, limit=self._page_size, commitment=FINALIZED
            )
            stop = False
            for entry in page:
                signature = entry.get("signature") if isinstance(entry, dict) else None
                if not isinstance(signature, str) or not signature:
                    raise ProviderError("Solana RPC returned a malformed signature entry", retryable=False, status=502)
                if signature in seen:
                    continue
                seen.add(signature)

                slot = entry.get("slot")
                if isinstance(slot, int) and slot > snapshot_slot:
                    continue

                block_time = entry.get("blockTime")
                if block_time is not None:
                    if block_time >= to_ts:
                        continue
                    if block_time < from_ts:
                        reached_boundary = True
                        stop = True
                        break

                if transaction_count >= max_transactions:
                    # An in-range signature exists beyond the limit: the window is not fully covered.
                    limit_hit = True
                    stop = True
                    break
                transaction_count += 1

                if entry.get("err") is not None:
                    failed_count += 1
                    continue

                try:
                    tx = self._rpc.get_transaction(signature, commitment=FINALIZED)
                except ProviderError:
                    tx = None
                if tx is None:
                    reasons.add(REASON_FETCH_FAILED)
                else:
                    transactions.append(tx)

            if stop:
                break
            if len(page) < self._page_size:
                # End of history: nothing older exists, so the window boundary is covered.
                reached_boundary = True
                break
            next_before = page[-1]["signature"]
            if next_before == before:
                raise ProviderError("Solana RPC pagination did not advance", retryable=False, status=502)
            before = next_before

        if limit_hit:
            reasons.add(REASON_LIMIT)
            reached_boundary = False
        elif not reached_boundary:
            reasons.add(REASON_BOUNDARY)

        return LiveResult(
            transactions=transactions,
            failed_count=failed_count,
            transaction_count=transaction_count,
            reasons=reasons,
            reached_time_boundary=reached_boundary,
            snapshot_slot=snapshot_slot,
        )
