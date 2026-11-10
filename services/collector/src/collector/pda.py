"""Program derived addresses (stdlib only), used to compute associated token account addresses.

An associated token account (ATA) address depends only on (wallet, token program, mint), so it can
be computed for accounts that are already closed and therefore invisible to getTokenAccountsByOwner.
"""
from __future__ import annotations

import hashlib

ASSOCIATED_TOKEN_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_INDEX = {char: i for i, char in enumerate(_ALPHABET)}
_P = 2 ** 255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P


def b58decode(value: str) -> bytes:
    number = 0
    for char in value:
        number = number * 58 + _INDEX[char]
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\0" * (len(value) - len(value.lstrip("1"))) + body


def b58encode(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    out = []
    while number:
        number, remainder = divmod(number, 58)
        out.append(_ALPHABET[remainder])
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + "".join(reversed(out))


def is_on_curve(point: bytes) -> bool:
    """Whether 32 bytes decompress to an ed25519 point (a PDA must not)."""
    y = int.from_bytes(point, "little") & ((1 << 255) - 1)
    if y >= _P:
        return False
    y2 = y * y % _P
    x2 = (y2 - 1) * pow(_D * y2 + 1, _P - 2, _P) % _P
    return x2 == 0 or pow(x2, (_P - 1) // 2, _P) == 1


def find_program_address(seeds: list[bytes], program_id: str) -> tuple[str, int]:
    program = b58decode(program_id)
    for bump in range(255, -1, -1):
        digest = hashlib.sha256(b"".join(seeds) + bytes([bump]) + program + b"ProgramDerivedAddress").digest()
        if not is_on_curve(digest):
            return b58encode(digest), bump
    raise ValueError("No viable program derived address")


def associated_token_address(wallet: str, mint: str, token_program: str) -> str:
    seeds = [b58decode(wallet), b58decode(token_program), b58decode(mint)]
    return find_program_address(seeds, ASSOCIATED_TOKEN_PROGRAM)[0]
