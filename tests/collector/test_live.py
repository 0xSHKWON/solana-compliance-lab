from datetime import datetime, timezone

import pytest

from collector.errors import ProviderError
from collector.live import LiveSource
from compliance_contracts.runtime import ContractViolation

ADDRESS = "Wallet1111111111111111111111111111111111111"
SNAPSHOT_SLOT = 1000


def ts(seconds):
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def entry(name, block_time, slot=900, err=None):
    return {"signature": name, "slot": slot, "err": err, "blockTime": block_time}


class FakeRpc:
    """Serves ``history`` (newest first) with real ``before`` semantics, or fixed ``pages``."""

    def __init__(self, history=(), pages=None, slot=SNAPSHOT_SLOT, transactions=None,
                 tx_errors=None, slot_error=None, signature_error=None, token_accounts=None, streams=None):
        self.history = list(history)
        self.token_accounts = token_accounts or {}
        self.streams = {key: list(value) for key, value in (streams or {}).items()}
        self.token_account_calls = []
        self.pages = list(pages) if pages is not None else None
        self.slot = slot
        self.transactions = transactions or {}
        self.tx_errors = tx_errors or {}
        self.slot_error = slot_error
        self.signature_error = signature_error
        self.signature_calls = []
        self.transaction_calls = []

    def get_slot(self, commitment="finalized"):
        if self.slot_error:
            raise self.slot_error
        return self.slot

    def get_token_accounts_by_owner(self, owner, program_id, commitment="finalized"):
        self.token_account_calls.append(program_id)
        return list(self.token_accounts.get(program_id, []))

    def get_signatures_for_address(self, address, before=None, limit=1000, commitment="finalized"):
        if address in self.streams:
            history = self.streams[address]
            start = 0 if before is None else next(i for i, e in enumerate(history) if e["signature"] == before) + 1
            return [dict(e) for e in history[start:start + limit]]
        self.signature_calls.append({"before": before, "limit": limit})
        if self.signature_error:
            raise self.signature_error
        if self.pages is not None:
            index = len(self.signature_calls) - 1
            return [dict(e) for e in self.pages[index]] if index < len(self.pages) else []
        start = 0
        if before is not None:
            start = next(i for i, e in enumerate(self.history) if e["signature"] == before) + 1
        return [dict(e) for e in self.history[start:start + limit]]

    def get_transaction(self, signature, commitment="finalized"):
        self.transaction_calls.append(signature)
        if signature in self.tx_errors:
            raise self.tx_errors[signature]
        return self.transactions.get(signature, {"slot": 900, "signature": signature})


START = ts(100)
END = ts(400)


def fetch(rpc, max_transactions=100, page_size=1000, start=START, end=END):
    # Selection tests run without closed-token-account discovery; discovery has its own tests below.
    return LiveSource(rpc, page_size=page_size, max_discovery_transactions=0).fetch(ADDRESS, start, end, max_transactions)


def test_pagination_follows_before_cursor_newest_first():
    history = [entry(f"s{i}", 390 - i * 10) for i in range(5)]  # 390..350, all in range
    rpc = FakeRpc(history)

    result = fetch(rpc, page_size=2)

    # The short third page is not trusted as the end of history; only the empty fourth page is.
    assert [c["before"] for c in rpc.signature_calls] == [None, "s1", "s3", "s4"]
    assert [t["signature"] for t in result.transactions] == ["s0", "s1", "s2", "s3", "s4"]
    assert result.transaction_count == 5
    assert result.failed_count == 0
    assert result.reasons == set()
    assert result.reached_time_boundary is True
    assert result.snapshot_slot == SNAPSHOT_SLOT


def test_time_boundary_stops_paging_and_skips_older_entries():
    history = [
        entry("too-new", 400),  # blockTime == to_time is excluded
        entry("in-a", 300),
        entry("in-b", 200),
        entry("old", 100),  # == from_time is in range
        entry("older", 50),
    ]
    rpc = FakeRpc(history)

    result = fetch(rpc, page_size=10)

    assert result.transaction_count == 3
    assert [t["signature"] for t in result.transactions] == ["in-a", "in-b", "old"]
    assert "older" not in rpc.transaction_calls
    assert result.reached_time_boundary is True
    assert result.reasons == set()
    assert len(rpc.signature_calls) == 1


def test_entry_strictly_before_from_time_sets_boundary():
    rpc = FakeRpc([entry("a", 300), entry("b", 99)])

    result = fetch(rpc, page_size=10)

    assert result.transaction_count == 1
    assert result.reached_time_boundary is True
    assert result.reasons == set()


def test_too_new_entries_are_skipped_and_not_counted():
    history = [entry("future", 450), entry("a", 300), entry("b", 200)]
    rpc = FakeRpc(history)

    result = fetch(rpc, max_transactions=2, page_size=10)

    assert result.transaction_count == 2
    assert "future" not in rpc.transaction_calls
    assert result.reasons == set()


def test_slot_above_snapshot_is_skipped():
    history = [entry("ahead", 300, slot=SNAPSHOT_SLOT + 1), entry("a", 200, slot=SNAPSHOT_SLOT)]
    rpc = FakeRpc(history)

    result = fetch(rpc, page_size=10)

    assert result.transaction_count == 1
    assert rpc.transaction_calls == ["a"]


def test_max_limit_reached_with_more_in_range_sets_limit_reason():
    history = [entry("a", 390), entry("b", 380), entry("c", 370), entry("d", 360)]
    rpc = FakeRpc(history)

    result = fetch(rpc, max_transactions=2, page_size=10)

    assert result.transaction_count == 2
    assert [t["signature"] for t in result.transactions] == ["a", "b"]
    assert "TRANSACTION_LIMIT_REACHED" in result.reasons
    assert result.reached_time_boundary is False


def test_exactly_max_with_history_end_has_no_limit_reason():
    rpc = FakeRpc([entry("a", 390), entry("b", 380), entry("c", 370)])

    result = fetch(rpc, max_transactions=3, page_size=10)

    assert result.transaction_count == 3
    assert result.reasons == set()
    assert result.reached_time_boundary is True


def test_exactly_max_then_older_entry_has_no_limit_reason():
    rpc = FakeRpc([entry("a", 390), entry("b", 380), entry("old", 50)])

    result = fetch(rpc, max_transactions=2, page_size=10)

    assert result.transaction_count == 2
    assert result.reasons == set()
    assert result.reached_time_boundary is True


def test_failed_entries_are_counted_but_not_fetched():
    history = [entry("ok", 390), entry("bad", 380, err={"InstructionError": [0, "Custom"]}), entry("ok2", 370)]
    rpc = FakeRpc(history)

    result = fetch(rpc, page_size=10)

    assert result.transaction_count == 3
    assert result.failed_count == 1
    assert sorted(rpc.transaction_calls) == ["ok", "ok2"]
    assert [t["signature"] for t in result.transactions] == ["ok", "ok2"]
    assert result.reasons == set()


def test_fetch_failure_records_reason_and_continues():
    history = [entry("a", 390), entry("b", 380), entry("c", 370)]
    rpc = FakeRpc(
        history,
        tx_errors={"a": ProviderError("upstream hiccup")},
        transactions={"b": None},
    )

    result = fetch(rpc, page_size=10)

    assert result.transaction_count == 3
    assert [t["signature"] for t in result.transactions] == ["c"]
    assert result.reasons == {"TRANSACTION_FETCH_FAILED"}
    assert result.reached_time_boundary is True


def test_history_shorter_than_range_reaches_boundary():
    rpc = FakeRpc([entry("a", 300)])

    result = fetch(rpc, page_size=1000)

    assert result.reached_time_boundary is True
    assert result.reasons == set()
    assert result.transaction_count == 1


def test_duplicate_signatures_across_pages_are_deduped():
    pages = [
        [entry("a", 390), entry("b", 380)],
        [entry("b", 380), entry("c", 370)],
        [],
    ]
    rpc = FakeRpc(pages=pages)

    result = fetch(rpc, page_size=2)

    assert result.transaction_count == 3
    assert sorted(rpc.transaction_calls) == ["a", "b", "c"]
    assert [t["signature"] for t in result.transactions] == ["a", "b", "c"]


def test_null_block_time_is_included():
    rpc = FakeRpc([entry("nullable", None)])

    result = fetch(rpc, page_size=10)

    assert result.transaction_count == 1
    assert [t["signature"] for t in result.transactions] == ["nullable"]


def test_get_slot_failure_propagates():
    rpc = FakeRpc([entry("a", 300)], slot_error=ProviderError("slot down"))

    with pytest.raises(ProviderError, match="slot down"):
        fetch(rpc)
    assert rpc.signature_calls == []


def test_signature_listing_failure_propagates():
    rpc = FakeRpc([entry("a", 300)], signature_error=ProviderError("rpc down"))

    with pytest.raises(ProviderError, match="rpc down"):
        fetch(rpc)


def test_naive_datetime_is_rejected():
    rpc = FakeRpc([])

    with pytest.raises(ContractViolation):
        LiveSource(rpc).fetch(ADDRESS, datetime(2026, 1, 1), END, 10)


def test_inverted_range_is_rejected():
    rpc = FakeRpc([])

    with pytest.raises(ContractViolation):
        fetch(rpc, start=END, end=START)


# --- token account streams, time budget ----------------------------------------------------

TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"


def test_token_account_signatures_are_merged_newest_first():
    rpc = FakeRpc(
        history=[entry("w2", 380, slot=920), entry("w1", 300, slot=850)],
        token_accounts={TOKEN: ["ata1"], TOKEN_2022: ["ata2"]},
        streams={"ata1": [entry("t1", 390, slot=950), entry("w2", 380, slot=920)],
                 "ata2": [entry("t2", 350, slot=880)]},
    )

    result = fetch(rpc, page_size=10)

    assert result.token_accounts == ["ata1", "ata2"]
    assert sorted(rpc.token_account_calls) == sorted([TOKEN, TOKEN_2022])
    assert [t["signature"] for t in result.transactions] == ["t1", "w2", "t2", "w1"]
    assert result.transaction_count == 4  # w2 appears in two streams but is one transaction
    assert result.reasons == set()
    assert result.reached_time_boundary is True


def test_limit_applies_to_the_merged_history():
    rpc = FakeRpc(
        history=[entry("w1", 300, slot=850)],
        token_accounts={TOKEN: ["ata1"]},
        streams={"ata1": [entry("t1", 390, slot=950), entry("t2", 380, slot=940), entry("t3", 370, slot=930)]},
    )

    result = fetch(rpc, max_transactions=2, page_size=10)

    assert [t["signature"] for t in result.transactions] == ["t1", "t2"]
    assert result.reasons == {"TRANSACTION_LIMIT_REACHED"}
    assert result.reached_time_boundary is False


def test_token_account_cap_reports_incomplete_window():
    rpc = FakeRpc(history=[entry("w1", 300)], token_accounts={TOKEN: ["a", "b", "c"]},
                  streams={"a": [], "b": [], "c": []})

    result = LiveSource(rpc, page_size=10, max_token_accounts=2).fetch(ADDRESS, START, END, 10)

    assert result.token_accounts == ["a", "b"]
    assert "TIME_BOUNDARY_NOT_REACHED" in result.reasons
    assert result.reached_time_boundary is False


class StepClock:
    """Each call advances time by ``step`` seconds."""

    def __init__(self, step):
        self.now, self.step = 0.0, step

    def __call__(self):
        self.now += self.step
        return self.now


def test_time_budget_exhausted_during_scan_is_partial():
    rpc = FakeRpc(history=[entry("a", 390)])

    result = LiveSource(rpc, page_size=10, time_budget=1.0, clock=StepClock(5.0)).fetch(ADDRESS, START, END, 10)

    assert "TIME_BOUNDARY_NOT_REACHED" in result.reasons
    assert result.reached_time_boundary is False


def test_time_budget_exhausted_during_fetch_is_partial():
    import threading

    release = threading.Event()

    class SlowRpc(FakeRpc):
        def get_transaction(self, signature, commitment="finalized"):
            if signature == "slow":
                release.wait(10)
            return super().get_transaction(signature, commitment)

    rpc = SlowRpc(history=[entry("fast", 390), entry("slow", 380)])
    try:
        # Generous budget: the fast fetch must finish well within it even on a loaded machine.
        result = LiveSource(rpc, page_size=10, time_budget=2.0, max_discovery_transactions=0).fetch(
            ADDRESS, START, END, 10)
    finally:
        release.set()

    assert [t["signature"] for t in result.transactions] == ["fast"]
    assert result.transaction_count == 2
    assert "TRANSACTION_FETCH_FAILED" in result.reasons
    assert result.reached_time_boundary is True


def test_short_page_from_a_capping_provider_is_not_end_of_history():
    """Regression: a provider returning fewer rows than requested must not end the scan early."""
    history = [entry(f"s{i}", 390 - i * 10) for i in range(5)]

    class CappingRpc(FakeRpc):
        def get_signatures_for_address(self, address, before=None, limit=1000, commitment="finalized"):
            return super().get_signatures_for_address(address, before=before, limit=1, commitment=commitment)

    result = fetch(CappingRpc(history), page_size=10)

    assert result.transaction_count == 5
    assert result.reasons == set()


def test_null_block_time_signature_is_dropped_when_transaction_is_outside_window():
    rpc = FakeRpc([entry("inside", 390), entry("unknown", None)],
                  transactions={"unknown": {"slot": 900, "blockTime": 50, "signature": "unknown"}})

    result = fetch(rpc, page_size=10)

    assert [t["signature"] for t in result.transactions] == ["inside"]
    assert result.transaction_count == 1


def test_malformed_block_time_is_a_provider_error_not_a_crash():
    rpc = FakeRpc([{"signature": "a", "slot": 900, "err": None, "blockTime": "390"}])
    with pytest.raises(ProviderError):
        fetch(rpc, page_size=10)


def test_deadline_is_bound_to_the_rpc_client():
    class BindingRpc(FakeRpc):
        bound = None

        def bind_deadline(self, deadline):
            BindingRpc.bound = deadline

    LiveSource(BindingRpc([]), time_budget=7.0, clock=lambda: 100.0).fetch(ADDRESS, START, END, 10)

    assert BindingRpc.bound == 107.0


def test_budget_exhausted_while_paging_marks_scan_incomplete():
    from collector.errors import BudgetExhausted

    class ExhaustedRpc(FakeRpc):
        def get_signatures_for_address(self, address, before=None, limit=1000, commitment="finalized"):
            if before is not None:
                raise BudgetExhausted()
            return super().get_signatures_for_address(address, before=before, limit=limit, commitment=commitment)

    result = fetch(ExhaustedRpc([entry("a", 390), entry("b", 380)]), page_size=2)

    assert [t["signature"] for t in result.transactions] == ["a", "b"]
    assert "TIME_BOUNDARY_NOT_REACHED" in result.reasons



# --- discovery of token accounts the wallet no longer holds -------------------------------------

def _close_tx(signature, account, owner=ADDRESS, block_time=500):
    return {"slot": 990, "blockTime": block_time, "meta": {"err": None, "preTokenBalances": [], "postTokenBalances": []},
            "transaction": {"signatures": [signature], "message": {"accountKeys": [owner, account], "instructions": [
                {"programId": TOKEN, "parsed": {"type": "closeAccount",
                                                "info": {"account": account, "destination": owner, "owner": owner}}}]}}}


def test_closed_token_account_is_discovered_from_a_later_wallet_transaction():
    """The wallet received into a token account in the window and closed it afterwards."""
    rpc = FakeRpc(
        history=[entry("close", 500, slot=990), entry("w1", 300, slot=850)],  # 'close' is newer than the window
        streams={"closed-ata": [entry("close", 500, slot=990), entry("deposit", 390, slot=950)]},
        transactions={"close": _close_tx("close", "closed-ata")},
    )

    result = LiveSource(rpc, page_size=10).fetch(ADDRESS, START, END, 10)

    assert result.token_accounts == ["closed-ata"]
    assert [t["signature"] for t in result.transactions] == ["deposit", "w1"]
    assert result.reasons == set()


def test_token_account_owned_in_window_balances_is_discovered():
    tx = {"slot": 850, "blockTime": 300, "meta": {"err": None, "postTokenBalances": [
        {"accountIndex": 1, "owner": ADDRESS, "mint": "m"}]},
          "transaction": {"signatures": ["w1"], "message": {"accountKeys": [ADDRESS, "old-ata"], "instructions": []}}}
    rpc = FakeRpc(history=[entry("w1", 300, slot=850)], streams={"old-ata": [entry("in", 350, slot=870)]},
                  transactions={"w1": tx})

    result = LiveSource(rpc, page_size=10).fetch(ADDRESS, START, END, 10)

    assert result.token_accounts == ["old-ata"]
    assert [row["signature"] for row in result.signatures] == ["in", "w1"]


def test_discovery_over_the_cap_reports_incomplete_window():
    rpc = FakeRpc(history=[entry(f"later{i}", 500 + i, slot=990) for i in range(3)][::-1])

    result = LiveSource(rpc, page_size=10, max_discovery_transactions=2).fetch(ADDRESS, START, END, 10)

    assert "TIME_BOUNDARY_NOT_REACHED" in result.reasons
    assert len(rpc.transaction_calls) == 2


def test_discovery_does_not_refetch_selected_transactions():
    rpc = FakeRpc(history=[entry("a", 390), entry("b", 380)])

    LiveSource(rpc, page_size=10).fetch(ADDRESS, START, END, 10)

    assert sorted(rpc.transaction_calls) == ["a", "b"]  # fetched once, during discovery


def test_owned_token_accounts_reads_balances_close_initialize_and_ata_create():
    from collector.live import owned_token_accounts

    tx = {"meta": {"preTokenBalances": [{"accountIndex": 1, "owner": ADDRESS}],
                   "postTokenBalances": [{"accountIndex": 2, "owner": "someone-else"}],
                   "innerInstructions": [{"index": 0, "instructions": [
                       {"programId": TOKEN_2022, "parsed": {"type": "initializeAccount3",
                                                            "info": {"account": "init", "owner": ADDRESS}}}]}]},
          "transaction": {"message": {"accountKeys": [ADDRESS, "bal", "other"], "instructions": [
              {"programId": TOKEN, "parsed": {"type": "closeAccount", "info": {"account": "closed", "owner": ADDRESS}}},
              {"programId": "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
               "parsed": {"type": "createIdempotent", "info": {"account": "ata", "wallet": ADDRESS}}},
              {"programId": TOKEN, "parsed": {"type": "closeAccount", "info": {"account": "x", "owner": "someone-else"}}},
          ]}}}

    assert owned_token_accounts(tx, ADDRESS) == {"bal", "init", "closed", "ata"}
