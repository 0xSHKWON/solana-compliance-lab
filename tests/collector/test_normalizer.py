"""Tests for collector.normalizer using jsonParsed getTransaction fixtures under data/rpc/."""
import copy
import dataclasses
import json
from pathlib import Path

import pytest
from compliance_contracts.runtime import ContractViolation, stable_id, validate

from collector.errors import ProviderError
from collector.normalizer import (
    OWNER_UNRESOLVED,
    PARSE_FAILED,
    TIMESTAMP_UNAVAILABLE,
    TOKEN_2022_PROGRAM,
    UNSUPPORTED_INSTRUCTION,
    NormalizeResult,
    normalize_transaction,
)

DATA = Path(__file__).parent / "data" / "rpc"

A = "9TLxza8f2iXiPwCsppACcVBvp69vJUb1uNS11wiRisLh"
B = "FRDZZQnRzK6raiGPktbpZFMxkXDe4ziEKkGaZak1HMuU"
C = "AhUi24v6XRQJYkANnF6N77NgBc1QgBjSPoYUej59SDbt"
D = "5txgY5wsXdzpt5GeFq36yNFtYRCQdG7adFbex8iX7gD5"
MINT_A = "3MTdEc3rvNavzm5Fe1LLyRdugey6VFRBtsptNKahymAF"
MINT_B = "FuPnEpzjYdHpdw3rUPHgw39NGajhmFhzJfBY3jYtvem6"
MINT_22 = "DWbfoyVJM5mQin9j3tcnQ9buZfLXF9n7mLi5dUZJggrf"
TA_A = "4zGgRQxHLyxC4cCkxqeFjbKrvQM3RAy1bb22ZHvHGvh3"
TA_B = "A6iXBBF8QGNjMNA9QdaASTi3EPq9NrUSsCEzz7YcAXyd"
TA_C = "8axw7jQzxsv5Htp4Md9oHfvaGMiPc61aTAhAr9adXXTu"
TA_D = "BiAU9N8yhZupr8LPXaEbd1M9aTS4U6geuh8Na88Hrufo"
TB_A = "3fGVRkNmgdyrY46emQYj6pw4rEPmZBwux2cuxy4XcBXD"
TB_B = "6BhuTRCovWUfSDPeUWfWV8Jeg6sE9Txk7u6BuPuRT9gn"
T22_A = "EL34YDvwFax6i37UUaABhH3rQjtrDMogeiM87nCP1tBe"
T22_B = "FNF4JSGgL1uBuQ2yKHpdgyuULkbMoxpp781B8cvtxxq3"
TA_NOBAL = "DrFcAKiQ8KHasSVUdQWhmgk2UaKdUJfgmBHQKj9VyxSv"
PROG_X = "F184voXi7TEzD6MTpfPhbmhvBGV8JKTjWG2Y1qEQ7AUV"
MAX_U64 = "18446744073709551615"


def load(name):
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def normalize_checked(tx, address):
    """Normalize and validate every produced transfer against the NormalizedTransfer schema."""
    result = normalize_transaction(tx, address)
    assert isinstance(result, NormalizeResult)
    assert isinstance(result.transfers, list)
    assert isinstance(result.reasons, frozenset)
    for transfer in result.transfers:
        validate("collector", "NormalizedTransfer", transfer)
    return result


def positions(result):
    return [(t["instructionIndex"], t["innerInstructionIndex"]) for t in result.transfers]


def test_sol_transfer_top_level():
    tx = load("sol_transfer")
    result = normalize_checked(tx, A)

    assert result.failed is False
    assert result.reasons == frozenset()
    assert len(result.transfers) == 1
    transfer = result.transfers[0]
    assert transfer["signature"] == tx["transaction"]["signatures"][0]
    assert transfer["slot"] == 300000001
    assert transfer["timestamp"] == "2026-01-01T00:00:00Z"
    assert transfer["instructionIndex"] == 0
    assert transfer["innerInstructionIndex"] is None
    assert transfer["transferOrdinal"] == 0
    assert transfer["fromAddress"] == A
    assert transfer["toAddress"] == B
    assert transfer["sourceAccount"] == A
    assert transfer["destinationAccount"] == B
    assert transfer["asset"] == {"type": "SOL", "mint": None, "decimals": 9}
    assert transfer["amountRaw"] == "1500000000"
    assert transfer["ownerResolved"] is True


def test_sol_transfer_visible_to_recipient():
    result = normalize_checked(load("sol_transfer"), B)
    assert positions(result) == [(0, None)]


def test_spl_transfer_checked_owners_come_from_token_balances():
    result = normalize_checked(load("spl_transfer_checked"), A)

    assert result.reasons == frozenset()
    assert len(result.transfers) == 1
    transfer = result.transfers[0]
    assert transfer["fromAddress"] == A
    assert transfer["toAddress"] == B
    assert transfer["sourceAccount"] == TA_A
    assert transfer["destinationAccount"] == TA_B
    assert transfer["asset"] == {"type": "SPL", "mint": MINT_A, "decimals": 6}
    assert transfer["amountRaw"] == "2500000"
    assert transfer["timestamp"] == "2026-01-01T00:01:00Z"
    assert transfer["ownerResolved"] is True


def test_spl_plain_transfer_resolves_mint_and_decimals_from_balances():
    result = normalize_checked(load("spl_transfer_plain"), B)

    assert result.reasons == frozenset()
    assert len(result.transfers) == 1
    transfer = result.transfers[0]
    assert transfer["asset"] == {"type": "SPL", "mint": MINT_B, "decimals": 9}
    assert transfer["amountRaw"] == "1000000000"
    assert transfer["fromAddress"] == A
    assert transfer["toAddress"] == B
    assert transfer["sourceAccount"] == TB_A
    assert transfer["destinationAccount"] == TB_B


def test_token_2022_transfer_checked_with_fee():
    result = normalize_checked(load("token2022_transfer_checked_with_fee"), A)

    assert result.reasons == frozenset()
    assert len(result.transfers) == 1
    transfer = result.transfers[0]
    assert transfer["asset"] == {"type": "TOKEN_2022", "mint": MINT_22, "decimals": 6}
    assert transfer["amountRaw"] == "5000000"
    assert transfer["fromAddress"] == A
    assert transfer["toAddress"] == B
    assert transfer["sourceAccount"] == T22_A
    assert transfer["destinationAccount"] == T22_B


def test_plain_transfer_under_token_2022_program_is_token_2022_asset():
    tx = load("spl_transfer_plain")
    tx["transaction"]["message"]["instructions"][0]["programId"] = TOKEN_2022_PROGRAM
    result = normalize_checked(tx, A)

    assert len(result.transfers) == 1
    assert result.transfers[0]["asset"]["type"] == "TOKEN_2022"


def test_inner_instruction_indices_and_order():
    result = normalize_checked(load("inner_instructions"), A)

    assert result.reasons == frozenset()
    assert positions(result) == [(0, None), (1, 0), (1, 1)]

    top, inner_token, inner_sol = result.transfers
    assert top["asset"]["type"] == "SOL"
    assert top["toAddress"] == B
    assert top["amountRaw"] == "1000000"

    assert inner_token["asset"] == {"type": "SPL", "mint": MINT_A, "decimals": 6}
    assert inner_token["fromAddress"] == A
    assert inner_token["toAddress"] == B
    assert inner_token["amountRaw"] == "42"

    assert inner_sol["asset"] == {"type": "SOL", "mint": None, "decimals": 9}
    assert inner_sol["toAddress"] == C
    assert inner_sol["amountRaw"] == "77"

    ids = [t["id"] for t in result.transfers]
    assert len(set(ids)) == len(ids)


def test_failed_transaction_has_no_transfers():
    result = normalize_checked(load("failed_transaction"), A)

    assert result.failed is True
    assert result.transfers == []
    assert result.reasons == frozenset()


def test_unresolved_owner_is_reported_and_not_filled_with_token_account():
    result = normalize_checked(load("owner_unresolved"), A)

    assert result.reasons == frozenset({OWNER_UNRESOLVED})
    assert len(result.transfers) == 1
    transfer = result.transfers[0]
    assert transfer["fromAddress"] == A
    assert transfer["toAddress"] is None
    assert transfer["destinationAccount"] == TA_NOBAL
    assert transfer["ownerResolved"] is False
    assert transfer["amountRaw"] == "100"


def test_unparsed_instructions_are_unsupported_and_parsed_non_transfers_ignored():
    result = normalize_checked(load("unsupported_instruction"), A)

    assert result.failed is False
    assert result.transfers == []
    assert result.reasons == frozenset({UNSUPPORTED_INSTRUCTION})


def test_other_program_instructions_are_ignored():
    result = normalize_checked(load("inner_instructions"), PROG_X)
    assert result.transfers == []
    assert result.reasons == frozenset()


def _sol_info(tx):
    return tx["transaction"]["message"]["instructions"][0]["parsed"]["info"]


MALFORMED_MUTATIONS = {
    "missing lamports": lambda info: info.pop("lamports"),
    "negative lamports": lambda info: info.update(lamports=-1),
    "float lamports": lambda info: info.update(lamports=1.5),
    "non-digit string amount": lambda info: info.update(lamports="12ab"),
    "boolean amount": lambda info: info.update(lamports=True),
    "non-base58 source": lambda info: info.update(source="0" + A[1:]),
    "source decodes to 44 bytes": lambda info: info.update(source="1" * 44),
    "missing destination": lambda info: info.pop("destination"),
}


@pytest.mark.parametrize("mutate", MALFORMED_MUTATIONS.values(), ids=MALFORMED_MUTATIONS.keys())
def test_malformed_transfer_is_skipped_without_raising(mutate):
    tx = load("sol_transfer")
    mutate(_sol_info(tx))

    result = normalize_transaction(tx, A)

    assert result.transfers == []
    assert result.reasons == frozenset({PARSE_FAILED})


def test_malformed_transfer_does_not_hide_valid_transfer_in_same_transaction():
    tx = load("sol_transfer")
    _sol_info(tx).pop("lamports")
    valid = load("sol_transfer")["transaction"]["message"]["instructions"][0]
    tx["transaction"]["message"]["instructions"].append(valid)

    result = normalize_checked(tx, A)

    assert positions(result) == [(1, None)]
    assert result.reasons == frozenset({PARSE_FAILED})


def test_token_transfer_without_token_amount_is_parse_failed():
    tx = load("spl_transfer_checked")
    del tx["transaction"]["message"]["instructions"][0]["parsed"]["info"]["tokenAmount"]

    result = normalize_checked(tx, A)

    assert result.transfers == []
    assert result.reasons == frozenset({PARSE_FAILED})


def test_plain_token_transfer_without_balances_has_unknown_mint_and_is_parse_failed():
    tx = load("spl_transfer_plain")
    tx["meta"]["preTokenBalances"] = []
    tx["meta"]["postTokenBalances"] = []

    result = normalize_checked(tx, A)

    assert result.transfers == []
    assert result.reasons == frozenset({PARSE_FAILED})


def test_malformed_transaction_result_raises_provider_error():
    tx = load("sol_transfer")
    del tx["transaction"]

    with pytest.raises(ProviderError) as info:
        normalize_transaction(tx, A)
    assert info.value.retryable is False


def test_invalid_wallet_address_argument_is_rejected():
    with pytest.raises(ContractViolation):
        normalize_transaction(load("sol_transfer"), "not-an-address")


def test_null_block_time_gives_null_timestamp_and_reason():
    result = normalize_checked(load("null_block_time"), A)

    assert len(result.transfers) == 1
    assert result.transfers[0]["timestamp"] is None
    assert result.reasons == frozenset({TIMESTAMP_UNAVAILABLE})


def test_transfers_not_involving_address_are_filtered():
    tx = load("multiple_transfers")

    only_a = normalize_checked(tx, A)
    assert positions(only_a) == [(0, None)]
    assert only_a.reasons == frozenset()

    for_c = normalize_checked(tx, C)
    assert positions(for_c) == [(1, None), (2, None)]
    assert for_c.transfers[0]["fromAddress"] == C
    assert for_c.transfers[0]["toAddress"] == D
    assert for_c.transfers[1]["sourceAccount"] == TA_C
    assert for_c.transfers[1]["destinationAccount"] == TA_D

    unrelated = normalize_checked(tx, PROG_X)
    assert unrelated.transfers == []


def test_ids_are_stable_and_deterministic():
    tx = load("inner_instructions")

    first = normalize_checked(tx, A)
    second = normalize_checked(copy.deepcopy(tx), A)
    assert first == second

    reordered = json.loads(json.dumps(tx, sort_keys=True))
    assert normalize_checked(reordered, A).transfers == first.transfers

    for transfer in first.transfers:
        expected = stable_id("transfer", {
            "signature": transfer["signature"],
            "instructionIndex": transfer["instructionIndex"],
            "innerInstructionIndex": transfer["innerInstructionIndex"],
            "transferOrdinal": transfer["transferOrdinal"],
        })
        assert transfer["id"] == expected

    ids = [t["id"] for t in first.transfers]
    assert len(set(ids)) == len(ids)


def test_transfer_id_does_not_depend_on_queried_address():
    tx = load("inner_instructions")
    by_a = {t["id"] for t in normalize_checked(tx, A).transfers}
    by_b = {t["id"] for t in normalize_checked(tx, B).transfers}

    assert by_b <= by_a
    assert len(by_b) == 2


def test_large_amounts_are_preserved_exactly_as_strings():
    result = normalize_checked(load("large_amounts"), A)

    assert positions(result) == [(0, None), (1, None)]
    sol, spl = result.transfers
    assert sol["amountRaw"] == MAX_U64
    assert spl["amountRaw"] == MAX_U64
    assert isinstance(sol["amountRaw"], str)
    assert spl["asset"] == {"type": "SPL", "mint": MINT_B, "decimals": 9}


def test_normalize_result_is_frozen():
    result = normalize_transaction(load("failed_transaction"), A)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.failed = False


def test_program_ids_decode_to_32_bytes():
    """Regression: a mistyped program ID silently drops every transfer of that program."""
    from compliance_contracts.runtime import base58_size
    from collector.normalizer import SYSTEM_PROGRAM, TOKEN_2022_PROGRAM, TOKEN_PROGRAM

    assert TOKEN_2022_PROGRAM == "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
    assert all(base58_size(program) == 32 for program in (SYSTEM_PROGRAM, TOKEN_PROGRAM, TOKEN_2022_PROGRAM))
