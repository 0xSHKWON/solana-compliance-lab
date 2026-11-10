"""Live transaction collection for one wallet over a half-open UTC window ``[from, to)``.

A wallet's history is the union of the signatures of the wallet itself and of every token
account it currently owns: an SPL transfer into a wallet's token account usually does not
list the wallet address, so a wallet-only scan silently misses incoming token transfers.

All provider work is bounded by a time budget that stays below the caller's read timeout.
Work that does not finish in time is reported as a coverage reason, never as an empty result.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone

from compliance_contracts.runtime import require

from .errors import BudgetExhausted, ProviderError

REASON_LIMIT = "TRANSACTION_LIMIT_REACHED"
REASON_FETCH_FAILED = "TRANSACTION_FETCH_FAILED"
REASON_BOUNDARY = "TIME_BOUNDARY_NOT_REACHED"
FINALIZED = "finalized"
TOKEN_PROGRAMS = (
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
)


@dataclass
class LiveResult:
    transactions: list[dict]
    failed_count: int
    transaction_count: int
    reasons: set[str] = field(default_factory=set)
    reached_time_boundary: bool = False
    snapshot_slot: int = 0
    token_accounts: list[str] = field(default_factory=list)
    # Selected signature entries (signature, slot, blockTime, err), newest first, failed ones included.
    signatures: list[dict] = field(default_factory=list)


@dataclass
class _Scan:
    entries: list[dict]
    complete: bool  # every in-range signature that can matter for the newest-N selection was seen


def _utc(value: datetime, name: str) -> datetime:
    require(
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None,
        f"{name} must be a timezone-aware datetime",
    )
    return value.astimezone(timezone.utc)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _signature_of(tx: dict):
    try:
        return tx["transaction"]["signatures"][0]
    except (KeyError, IndexError, TypeError):
        return None


def _newest_first(entry: dict):
    slot = entry.get("slot")
    block_time = entry.get("blockTime")
    return (-(slot if isinstance(slot, int) else -1), -(block_time if isinstance(block_time, int) else 0),
            entry["signature"])


class LiveSource:
    def __init__(self, rpc, page_size: int = 1000, max_pages: int = 50, max_token_accounts: int = 100,
                 fetch_workers: int = 16, time_budget: float = 20.0, clock=time.monotonic) -> None:
        require(page_size >= 1, "page_size must be positive")
        require(max_pages >= 1, "max_pages must be positive")
        require(max_token_accounts >= 0, "max_token_accounts must not be negative")
        require(fetch_workers >= 1, "fetch_workers must be positive")
        require(time_budget > 0, "time_budget must be positive")
        self._rpc = rpc
        self._page_size = page_size
        # Bounds the signature scan for very busy addresses whose window lies far in the past.
        self._max_pages = max_pages
        self._max_token_accounts = max_token_accounts
        self._workers = fetch_workers
        self._budget = time_budget
        self._clock = clock

    def fetch(self, address: str, from_time: datetime, to_time: datetime, max_transactions: int) -> LiveResult:
        start = _utc(from_time, "from_time")
        end = _utc(to_time, "to_time")
        require(start < end, "Empty or inverted time range")
        require(max_transactions >= 1, "max_transactions must be positive")
        deadline = self._clock() + self._budget
        bind = getattr(self._rpc, "bind_deadline", None)
        if callable(bind):
            bind(deadline)  # bounds every provider call, including retries, by the same budget
        reasons: set[str] = set()

        snapshot_slot = self._rpc.get_slot(commitment=FINALIZED)
        token_accounts = self._token_accounts(address)
        if len(token_accounts) > self._max_token_accounts:
            # Unscanned token accounts may hold in-range transfers: the window is not fully covered.
            token_accounts = token_accounts[:self._max_token_accounts]
            reasons.add(REASON_BOUNDARY)

        scan_args = (start.timestamp(), end.timestamp(), max_transactions, snapshot_slot, deadline)
        streams = [address, *token_accounts]
        with ThreadPoolExecutor(max_workers=min(self._workers, len(streams))) as pool:
            scans = list(pool.map(lambda stream: self._scan(stream, *scan_args), streams))

        merged: dict[str, dict] = {}
        for scan in scans:
            for entry in scan.entries:
                merged.setdefault(entry["signature"], entry)
        ordered = sorted(merged.values(), key=_newest_first)
        selected = ordered[:max_transactions]
        limit_hit = len(ordered) > max_transactions
        if limit_hit:
            reasons.add(REASON_LIMIT)
        if not all(scan.complete for scan in scans):
            reasons.add(REASON_BOUNDARY)

        failed = [entry for entry in selected if entry.get("err") is not None]
        to_fetch = [entry["signature"] for entry in selected if entry.get("err") is None]
        transactions, fetch_complete = self._fetch_all(to_fetch, deadline)
        if not fetch_complete:
            reasons.add(REASON_FETCH_FAILED)
        # A signature listed without blockTime was kept as a candidate; drop it if the transaction itself
        # turns out to lie outside the window, so every reported transfer is inside [from, to).
        inside = [tx for tx in transactions if not _is_int(tx.get("blockTime"))
                  or start.timestamp() <= tx["blockTime"] < end.timestamp()]
        outside = {_signature_of(tx) for tx in transactions} - {_signature_of(tx) for tx in inside}
        outside_count = len(transactions) - len(inside)
        transactions = inside
        signatures = [{key: entry.get(key) for key in ("signature", "slot", "blockTime", "err")}
                      for entry in selected if entry["signature"] not in outside]

        return LiveResult(
            transactions=transactions,
            failed_count=len(failed),
            transaction_count=len(selected) - outside_count,
            reasons=reasons,
            reached_time_boundary=not reasons & {REASON_LIMIT, REASON_BOUNDARY},
            snapshot_slot=snapshot_slot,
            token_accounts=token_accounts,
            signatures=signatures,
        )

    def _token_accounts(self, owner: str) -> list[str]:
        accounts: set[str] = set()
        for program in TOKEN_PROGRAMS:
            accounts.update(self._rpc.get_token_accounts_by_owner(owner, program, commitment=FINALIZED))
        accounts.discard(owner)
        return sorted(accounts)

    def _scan(self, stream: str, from_ts: float, to_ts: float, max_transactions: int,
              snapshot_slot: int, deadline: float) -> _Scan:
        """In-range signatures of one address, newest first.

        Stops early once ``max_transactions + 1`` in-range signatures are known: anything older in
        this stream cannot be among the newest ``max_transactions`` of the merged history.
        """
        seen: set[str] = set()
        entries: list[dict] = []
        before: str | None = None
        for _ in range(self._max_pages):
            if self._clock() >= deadline:
                return _Scan(entries, False)
            try:
                page = self._rpc.get_signatures_for_address(
                    stream, before=before, limit=self._page_size, commitment=FINALIZED
                )
            except BudgetExhausted:
                return _Scan(entries, False)
            if not isinstance(page, list):
                raise ProviderError("Solana RPC returned an invalid signature list", retryable=False, status=502)
            for entry in page:
                signature = entry.get("signature") if isinstance(entry, dict) else None
                if not isinstance(signature, str) or not signature:
                    raise ProviderError("Solana RPC returned a malformed signature entry", retryable=False, status=502)
                slot, block_time = entry.get("slot"), entry.get("blockTime")
                if not _is_int(slot) or not (block_time is None or _is_int(block_time)):
                    raise ProviderError("Solana RPC returned a malformed signature entry", retryable=False, status=502)
                if signature in seen:
                    continue
                seen.add(signature)
                if slot > snapshot_slot:
                    continue
                if block_time is not None:
                    if block_time >= to_ts:
                        continue
                    if block_time < from_ts:
                        return _Scan(entries, True)
                entries.append(entry)
                if len(entries) > max_transactions:
                    return _Scan(entries, True)
            if not page:
                # Only an empty page proves the end of history: some providers return short pages early.
                return _Scan(entries, True)
            next_before = page[-1]["signature"]
            if next_before == before:
                raise ProviderError("Solana RPC pagination did not advance", retryable=False, status=502)
            before = next_before
        return _Scan(entries, False)  # page cap reached before the time boundary

    def _fetch_all(self, signatures: list[str], deadline: float) -> tuple[list[dict], bool]:
        """Fetch transactions concurrently, keeping the newest-first order of ``signatures``."""
        if not signatures:
            return [], True

        def one(signature):
            try:
                return self._rpc.get_transaction(signature, commitment=FINALIZED)
            except ProviderError:
                return None

        pool = ThreadPoolExecutor(max_workers=min(self._workers, len(signatures)))
        try:
            futures = [pool.submit(one, signature) for signature in signatures]
            done, pending = wait(futures, timeout=max(0.0, deadline - self._clock()))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        transactions = [future.result() for future in futures if future in done]
        complete = not pending and all(tx is not None for tx in transactions)
        return [tx for tx in transactions if tx is not None], complete
