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
ASSOCIATED_TOKEN_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
_INITIALIZE_ACCOUNT = frozenset({"initializeAccount", "initializeAccount2", "initializeAccount3"})


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
    after: list[dict] = field(default_factory=list)  # signatures newer than the window (discovery only)
    after_complete: bool = True


def _utc(value: datetime, name: str) -> datetime:
    require(
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None,
        f"{name} must be a timezone-aware datetime",
    )
    return value.astimezone(timezone.utc)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def owned_token_accounts(tx: dict, owner: str) -> set[str]:
    """Token accounts that a transaction shows ``owner`` owning, including ones it creates or closes.

    Closing a token account needs the owner's signature and an associated token account is created
    with the wallet as an account key, so these transactions appear in the wallet's own history even
    after the token account itself is gone.
    """
    found: set[str] = set()
    try:
        message = tx["transaction"]["message"]
        keys = [k.get("pubkey") if isinstance(k, dict) else k for k in message["accountKeys"]]
        meta = tx.get("meta") or {}
    except (KeyError, TypeError):
        return found
    for section in ("preTokenBalances", "postTokenBalances"):
        for entry in meta.get(section) or []:
            index = entry.get("accountIndex") if isinstance(entry, dict) else None
            if entry.get("owner") == owner and _is_int(index) and 0 <= index < len(keys):
                found.add(keys[index])
    instructions = list(message.get("instructions") or [])
    for group in meta.get("innerInstructions") or []:
        if isinstance(group, dict):
            instructions.extend(group.get("instructions") or [])
    for ix in instructions:
        parsed = ix.get("parsed") if isinstance(ix, dict) else None
        if not isinstance(parsed, dict) or not isinstance(parsed.get("info"), dict):
            continue
        info, kind, program = parsed["info"], parsed.get("type"), ix.get("programId")
        if program in TOKEN_PROGRAMS and (kind == "closeAccount" or kind in _INITIALIZE_ACCOUNT):
            if info.get("owner") == owner and isinstance(info.get("account"), str):
                found.add(info["account"])
        elif program == ASSOCIATED_TOKEN_PROGRAM and kind in ("create", "createIdempotent"):
            if info.get("wallet") == owner and isinstance(info.get("account"), str):
                found.add(info["account"])
    found.discard(owner)
    return found


def _newest_first(entry: dict):
    slot = entry.get("slot")
    block_time = entry.get("blockTime")
    return (-(slot if isinstance(slot, int) else -1), -(block_time if isinstance(block_time, int) else 0),
            entry["signature"])


class LiveSource:
    def __init__(self, rpc, page_size: int = 1000, max_pages: int = 50, max_token_accounts: int = 100,
                 fetch_workers: int = 16, time_budget: float = 20.0, max_discovery_transactions: int = 1000,
                 clock=time.monotonic) -> None:
        require(page_size >= 1, "page_size must be positive")
        require(max_pages >= 1, "max_pages must be positive")
        require(max_token_accounts >= 0, "max_token_accounts must not be negative")
        require(fetch_workers >= 1, "fetch_workers must be positive")
        require(time_budget > 0, "time_budget must be positive")
        require(max_discovery_transactions >= 0, "max_discovery_transactions must not be negative")
        # 0 disables discovery of token accounts the wallet no longer holds.
        self._max_discovery = max_discovery_transactions
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
            scans = list(pool.map(
                lambda stream: self._scan(stream, *scan_args, collect_after=stream == address), streams))

        # Discovery: token accounts the wallet held in the window but has since closed are not returned by
        # getTokenAccountsByOwner. Their creation/closing transactions are in the wallet's own history
        # (in the window or after it), so read those transactions and scan any token account found there.
        cache: dict[str, dict] = {}
        if self._max_discovery:
            wallet_scan = scans[0]
            candidates = [e for e in wallet_scan.after + wallet_scan.entries if e.get("err") is None]
            complete = wallet_scan.after_complete and len(candidates) <= self._max_discovery
            fetched, fetch_complete = self._fetch_all([e["signature"] for e in candidates[:self._max_discovery]],
                                                      deadline)
            cache.update(fetched)
            if not (complete and fetch_complete):
                reasons.add(REASON_BOUNDARY)  # a closed token account may have been missed
            discovered = set()
            for tx in fetched.values():
                discovered |= owned_token_accounts(tx, address)
            extra = sorted(discovered - set(token_accounts) - {address})
            room = max(0, self._max_token_accounts - len(token_accounts))
            if len(extra) > room:
                extra = extra[:room]
                reasons.add(REASON_BOUNDARY)
            if extra:
                with ThreadPoolExecutor(max_workers=min(self._workers, len(extra))) as pool:
                    scans += list(pool.map(lambda stream: self._scan(stream, *scan_args), extra))
                token_accounts = sorted({*token_accounts, *extra})

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
        to_fetch = [entry["signature"] for entry in selected
                    if entry.get("err") is None and entry["signature"] not in cache]
        fetched, fetch_complete = self._fetch_all(to_fetch, deadline)
        cache.update(fetched)
        transactions = [cache[entry["signature"]] for entry in selected
                        if entry.get("err") is None and entry["signature"] in cache]
        if not fetch_complete:
            reasons.add(REASON_FETCH_FAILED)
        # A signature listed without blockTime was kept as a candidate; drop it if the transaction itself
        # turns out to lie outside the window, so every reported transfer is inside [from, to).
        outside = {entry["signature"] for entry in selected if entry["signature"] in cache
                   and _is_int(cache[entry["signature"]].get("blockTime"))
                   and not start.timestamp() <= cache[entry["signature"]]["blockTime"] < end.timestamp()}
        transactions = [tx for tx, entry in zip(transactions, [e for e in selected if e.get("err") is None
                                                               and e["signature"] in cache])
                        if entry["signature"] not in outside]
        outside_count = len(outside)
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
              snapshot_slot: int, deadline: float, collect_after: bool = False) -> _Scan:
        """In-range signatures of one address, newest first.

        Stops early once ``max_transactions + 1`` in-range signatures are known: anything older in
        this stream cannot be among the newest ``max_transactions`` of the merged history.
        """
        seen: set[str] = set()
        entries: list[dict] = []
        after: list[dict] = []
        passed_window_end = False  # every signature newer than the window has been listed
        before: str | None = None

        def result(complete):
            return _Scan(entries, complete, after, complete or passed_window_end)

        for _ in range(self._max_pages):
            if self._clock() >= deadline:
                return result(False)
            try:
                page = self._rpc.get_signatures_for_address(
                    stream, before=before, limit=self._page_size, commitment=FINALIZED
                )
            except BudgetExhausted:
                return result(False)
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
                        if collect_after and len(after) <= self._max_discovery:
                            after.append(entry)  # one past the cap so an overflow is detectable
                        continue
                    passed_window_end = True
                    if block_time < from_ts:
                        return result(True)
                entries.append(entry)
                if len(entries) > max_transactions:
                    return result(True)
            if not page:
                # Only an empty page proves the end of history: some providers return short pages early.
                return result(True)
            next_before = page[-1]["signature"]
            if next_before == before:
                raise ProviderError("Solana RPC pagination did not advance", retryable=False, status=502)
            before = next_before
        return result(False)  # page cap reached before the time boundary

    def _fetch_all(self, signatures: list[str], deadline: float) -> tuple[dict[str, dict], bool]:
        """Fetch transactions concurrently; returns {signature: transaction} and whether all arrived."""
        if not signatures:
            return {}, True

        def one(signature):
            try:
                return self._rpc.get_transaction(signature, commitment=FINALIZED)
            except ProviderError:
                return None

        pool = ThreadPoolExecutor(max_workers=min(self._workers, len(signatures)))
        try:
            futures = {signature: pool.submit(one, signature) for signature in signatures}
            done, pending = wait(futures.values(), timeout=max(0.0, deadline - self._clock()))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        result = {signature: future.result() for signature, future in futures.items() if future in done}
        complete = not pending and all(tx is not None for tx in result.values())
        return {signature: tx for signature, tx in result.items() if tx is not None}, complete
