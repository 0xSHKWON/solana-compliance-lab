"""Pure normalizer: Solana jsonParsed getTransaction result -> NormalizedTransfer dicts.

No I/O. Failures of a single instruction are reported as coverage reasons; only a
structurally broken transaction result raises (ProviderError) or an invalid address
argument raises (ContractViolation).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from compliance_contracts.runtime import ContractViolation, base58_size, stable_id

from collector.errors import ProviderError

SYSTEM_PROGRAM = "11111111111111111111111111111111"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

SOL_DECIMALS = 9

PARSE_FAILED = "PARSE_FAILED"
UNSUPPORTED_INSTRUCTION = "UNSUPPORTED_INSTRUCTION"
OWNER_UNRESOLVED = "OWNER_UNRESOLVED"
TIMESTAMP_UNAVAILABLE = "TIMESTAMP_UNAVAILABLE"

_BASE58_RE = re.compile(r"[1-9A-HJ-NP-Za-km-z]+")
_DIGITS_RE = re.compile(r"[0-9]+")


@dataclass(frozen=True)
class NormalizeResult:
    transfers: list[dict]
    reasons: frozenset[str]
    failed: bool


@dataclass(frozen=True)
class _TokenAccount:
    owner: str | None
    mint: str | None
    decimals: int | None


@dataclass(frozen=True)
class _Movement:
    asset_type: str  # SOL / SPL / TOKEN_2022
    source: str  # sourceAccount
    destination: str  # destinationAccount
    from_owner: str | None
    to_owner: str | None
    amount_raw: str
    mint: str | None
    decimals: int


class _Unsupported(Exception):
    """Instruction of a tracked program without parsed data."""


class _Malformed(Exception):
    """Instruction that claims to be a transfer but cannot be read safely."""


def normalize_transaction(tx: dict, address: str, related_accounts=()) -> NormalizeResult:
    """Normalize one transaction for ``address``.

    ``related_accounts`` are token accounts known to belong to ``address``. A transfer touching one
    of them is kept even when the token balances do not reveal the owner; the owner is still left
    unresolved rather than inferred.
    """
    if not _is_address(address):
        raise ContractViolation("Invalid wallet address", "INVALID_REQUEST", 400)
    tracked = {address, *related_accounts}
    if not isinstance(tx, dict):
        raise _malformed_result()
    meta = tx.get("meta")
    if not isinstance(meta, dict):
        raise _malformed_result()
    if meta.get("err") is not None:
        return NormalizeResult(transfers=[], reasons=frozenset(), failed=True)

    slot = tx.get("slot")
    block_time = tx.get("blockTime")
    transaction = tx.get("transaction")
    if not _is_non_negative_int(slot) or (block_time is not None and not _is_non_negative_int(block_time)):
        raise _malformed_result()
    if not isinstance(transaction, dict):
        raise _malformed_result()
    signatures = transaction.get("signatures")
    if not isinstance(signatures, list) or not signatures or not _is_signature(signatures[0]):
        raise _malformed_result()
    signature = signatures[0]
    message = transaction.get("message")
    if not isinstance(message, dict):
        raise _malformed_result()
    keys = _account_keys(message)
    instructions = message.get("instructions")
    inner_groups = meta.get("innerInstructions") or []
    if not isinstance(instructions, list) or not isinstance(inner_groups, list):
        raise _malformed_result()

    token_index = _token_index(meta, keys)
    reasons: set[str] = set()

    entries: list[tuple[int, int | None, Any]] = [(i, None, ix) for i, ix in enumerate(instructions)]
    for group in inner_groups:
        if (not isinstance(group, dict) or not _is_non_negative_int(group.get("index"))
                or not isinstance(group.get("instructions"), list)):
            reasons.add(PARSE_FAILED)  # cannot attribute this group to a parent instruction
            continue
        for position, ix in enumerate(group["instructions"]):
            entries.append((group["index"], position, ix))

    found: list[tuple[int, int | None, _Movement]] = []
    for index, inner, ix in entries:
        try:
            movement = _movement(ix, token_index)
        except _Unsupported:
            reasons.add(UNSUPPORTED_INSTRUCTION)
            continue
        except _Malformed:
            reasons.add(PARSE_FAILED)
            continue
        if movement is not None:
            found.append((index, inner, movement))

    timestamp = _timestamp(block_time)
    transfers: list[dict] = []
    seen: set[tuple[int, int | None]] = set()
    for index, inner, movement in sorted(found, key=lambda item: (item[0], -1 if item[1] is None else item[1])):
        if tracked.isdisjoint((movement.from_owner, movement.to_owner, movement.source, movement.destination)):
            continue
        if (index, inner) in seen:
            continue
        seen.add((index, inner))
        owner_resolved = movement.from_owner is not None and movement.to_owner is not None
        if not owner_resolved:
            reasons.add(OWNER_UNRESOLVED)
        if timestamp is None:
            reasons.add(TIMESTAMP_UNAVAILABLE)
        transfers.append({
            "id": stable_id("transfer", {
                "signature": signature,
                "instructionIndex": index,
                "innerInstructionIndex": inner,
                "transferOrdinal": 0,
            }),
            "signature": signature,
            "slot": slot,
            "timestamp": timestamp,
            "instructionIndex": index,
            "innerInstructionIndex": inner,
            "transferOrdinal": 0,
            "fromAddress": movement.from_owner,
            "toAddress": movement.to_owner,
            "sourceAccount": movement.source,
            "destinationAccount": movement.destination,
            "asset": {
                "type": movement.asset_type,
                "mint": movement.mint,
                "decimals": movement.decimals,
            },
            "amountRaw": movement.amount_raw,
            "ownerResolved": owner_resolved,
        })

    return NormalizeResult(transfers=transfers, reasons=frozenset(reasons), failed=False)


def _movement(ix: Any, token_index: dict[str, _TokenAccount]) -> _Movement | None:
    """Return the transfer described by an instruction, None when it is not a tracked transfer."""
    if not isinstance(ix, dict) or not isinstance(ix.get("programId"), str):
        raise _Malformed()
    program_id = ix["programId"]
    if program_id not in (SYSTEM_PROGRAM, TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
        return None
    parsed = ix.get("parsed")
    if not isinstance(parsed, dict):
        raise _Unsupported()
    kind = parsed.get("type")
    info = parsed.get("info")

    if program_id == SYSTEM_PROGRAM:
        if kind not in ("transfer", "transferWithSeed"):
            return None
        return _sol_movement(info)

    tracked_kinds = {"transfer", "transferChecked"}
    if program_id == TOKEN_2022_PROGRAM:
        tracked_kinds.add("transferCheckedWithFee")
    if kind not in tracked_kinds:
        return None
    asset_type = "TOKEN_2022" if program_id == TOKEN_2022_PROGRAM else "SPL"
    return _token_movement(kind, info, asset_type, token_index)


def _sol_movement(info: Any) -> _Movement:
    if not isinstance(info, dict):
        raise _Malformed()
    source = _address_field(info, "source")
    destination = _address_field(info, "destination")
    lamports = _amount_field(info, "lamports")
    return _Movement("SOL", source, destination, source, destination, lamports, None, SOL_DECIMALS)


def _token_movement(kind: str, info: Any, asset_type: str, token_index: dict[str, _TokenAccount]) -> _Movement:
    if not isinstance(info, dict):
        raise _Malformed()
    source = _address_field(info, "source")
    destination = _address_field(info, "destination")
    if kind == "transfer":
        amount = _amount_field(info, "amount")
        mint = None
        decimals = None
    else:
        token_amount = info.get("tokenAmount")
        if not isinstance(token_amount, dict):
            raise _Malformed()
        amount = _amount_field(token_amount, "amount")
        decimals = _decimals_value(token_amount.get("decimals"))
        mint = _address_field(info, "mint") if info.get("mint") is not None else None

    source_account = token_index.get(source)
    destination_account = token_index.get(destination)
    if mint is None:
        mint = _first(source_account and source_account.mint, destination_account and destination_account.mint)
    if decimals is None:
        decimals = _first(source_account and source_account.decimals, destination_account and destination_account.decimals)
    if mint is None or decimals is None:
        raise _Malformed()  # mint and decimals must be known to report a raw amount

    return _Movement(
        asset_type=asset_type,
        source=source,
        destination=destination,
        from_owner=source_account.owner if source_account else None,
        to_owner=destination_account.owner if destination_account else None,
        amount_raw=amount,
        mint=mint,
        decimals=decimals,
    )


def _token_index(meta: dict, keys: list[str]) -> dict[str, _TokenAccount]:
    """Map token account address -> owner/mint/decimals seen in pre/post token balances."""
    index: dict[str, _TokenAccount] = {}
    for section in ("preTokenBalances", "postTokenBalances"):
        entries = meta.get(section) or []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            position = entry.get("accountIndex")
            if not _is_non_negative_int(position) or position >= len(keys):
                continue
            account = keys[position]
            ui_amount = entry.get("uiTokenAmount")
            decimals = _decimals_value(ui_amount.get("decimals")) if isinstance(ui_amount, dict) else None
            owner = entry.get("owner") if _is_address(entry.get("owner")) else None
            mint = entry.get("mint") if _is_address(entry.get("mint")) else None
            previous = index.get(account, _TokenAccount(None, None, None))
            index[account] = _TokenAccount(
                owner=_first(previous.owner, owner),
                mint=_first(previous.mint, mint),
                decimals=_first(previous.decimals, decimals),
            )
    return index


def _account_keys(message: dict) -> list[str]:
    raw_keys = message.get("accountKeys")
    if not isinstance(raw_keys, list):
        raise _malformed_result()
    keys: list[str] = []
    for item in raw_keys:
        pubkey = item.get("pubkey") if isinstance(item, dict) else item
        if not isinstance(pubkey, str):
            raise _malformed_result()
        keys.append(pubkey)
    return keys


def _address_field(info: dict, name: str) -> str:
    value = info.get(name)
    if not _is_address(value):
        raise _Malformed()
    return value


def _amount_field(info: dict, name: str) -> str:
    value = info.get(name)
    if isinstance(value, bool):
        raise _Malformed()
    if isinstance(value, int):
        if value < 0:
            raise _Malformed()
        return str(value)
    if isinstance(value, str) and _DIGITS_RE.fullmatch(value):
        return str(int(value))
    raise _Malformed()


def _decimals_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
        raise _Malformed()
    return value


def _timestamp(block_time: int | None) -> str | None:
    if block_time is None:
        return None
    return datetime.fromtimestamp(block_time, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_address(value: Any) -> bool:
    return (isinstance(value, str) and 32 <= len(value) <= 44
            and _BASE58_RE.fullmatch(value) is not None and base58_size(value) == 32)


def _is_signature(value: Any) -> bool:
    return (isinstance(value, str) and 64 <= len(value) <= 88
            and _BASE58_RE.fullmatch(value) is not None and base58_size(value) == 64)


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None and value is not False and value != "":
            return value
    return None


def _malformed_result() -> ProviderError:
    return ProviderError("Malformed transaction result", retryable=False, status=502)
