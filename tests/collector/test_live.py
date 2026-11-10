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
                 tx_errors=None, slot_error=None, signature_error=None):
        self.history = list(history)
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

    def get_signatures_for_address(self, address, before=None, limit=1000, commitment="finalized"):
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
    return LiveSource(rpc, page_size=page_size).fetch(ADDRESS, start, end, max_transactions)


def test_pagination_follows_before_cursor_newest_first():
    history = [entry(f"s{i}", 390 - i * 10) for i in range(5)]  # 390..350, all in range
    rpc = FakeRpc(history)

    result = fetch(rpc, page_size=2)

    assert [c["before"] for c in rpc.signature_calls] == [None, "s1", "s3"]
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
    assert rpc.transaction_calls == ["ok", "ok2"]
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
    assert rpc.transaction_calls == ["a", "b", "c"]
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
