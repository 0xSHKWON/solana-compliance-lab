import json

import pytest

from collector import labels
from collector.errors import CollectionError
from compliance_contracts.runtime import ContractViolation

ADDR_A = "8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR"
ADDR_B = "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"
ADDR_SYSTEM = "11111111111111111111111111111111"
REPO_ROOT = labels.REPO_ROOT


def dataset(entries, source="TEST_FIXTURE", **overrides):
    data = {
        "source": source,
        "version": "1.0.0",
        "fetchedAt": "2026-11-02T00:00:00Z",
        "reference": None,
        "entries": entries,
    }
    data.update(overrides)
    return data


def write(tmp_path, data, name="labels.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def no_label_env(monkeypatch):
    monkeypatch.delenv(labels.DATASET_ENV, raising=False)


def test_default_path_is_under_collector_data_directory():
    assert labels.DEFAULT_DATASET_PATH == REPO_ROOT / "services" / "collector" / "data" / "labels" / "ofac-sdn.json"


def test_load_reads_metadata_from_explicit_path(tmp_path):
    path = write(tmp_path, dataset([{"address": ADDR_A, "type": "SANCTIONED", "referenceId": "ref-1"}]))
    loaded = labels.LabelDataset.load(path)
    assert loaded.metadata() == {"source": "TEST_FIXTURE", "version": "1.0.0", "fetchedAt": "2026-11-02T00:00:00Z"}


def test_env_override_selects_dataset_when_no_path_given(tmp_path, monkeypatch):
    path = write(tmp_path, dataset([], source="OFAC_SDN", version="2026-11-01"), "env.json")
    monkeypatch.setenv(labels.DATASET_ENV, str(path))
    assert labels.LabelDataset.load().metadata()["source"] == "OFAC_SDN"


def test_default_path_used_when_no_env_and_no_path(tmp_path, monkeypatch):
    path = write(tmp_path, dataset([]), "default.json")
    monkeypatch.setattr(labels, "DEFAULT_DATASET_PATH", path)
    assert labels.LabelDataset.load().metadata()["version"] == "1.0.0"


def test_labels_are_sorted_deduplicated_and_filtered(tmp_path):
    entries = [
        {"address": ADDR_B, "type": "SANCTIONED", "referenceId": "ref-2"},
        {"address": ADDR_A, "type": "SANCTIONED", "referenceId": "ref-9"},
        {"address": ADDR_A, "type": "SANCTIONED", "referenceId": "ref-1"},
        {"address": ADDR_A, "type": "SANCTIONED", "referenceId": "ref-1"},
        {"address": ADDR_SYSTEM, "type": "OTHER", "referenceId": "ref-3"},
    ]
    loaded = labels.LabelDataset.load(write(tmp_path, dataset(entries)))
    result = loaded.labels_for([ADDR_B, ADDR_A])
    # Sorted by address string (ADDR_B "4..." < ADDR_A "8..."), then referenceId.
    assert [(row["address"], row["referenceId"]) for row in result] == [
        (ADDR_B, "ref-2"), (ADDR_A, "ref-1"), (ADDR_A, "ref-9"),
    ]
    assert result[1] == {
        "address": ADDR_A,
        "network": "mainnet-beta",
        "type": "SANCTIONED",
        "source": "TEST_FIXTURE",
        "referenceId": "ref-1",
    }


def test_labels_for_unknown_addresses_is_empty(tmp_path):
    loaded = labels.LabelDataset.load(write(tmp_path, dataset([{"address": ADDR_A, "type": "OTHER", "referenceId": "r"}])))
    assert loaded.labels_for([ADDR_B]) == []
    assert loaded.labels_for([]) == []


def test_same_reference_id_on_one_address_keeps_one_label(tmp_path):
    entries = [
        {"address": ADDR_A, "type": "OTHER", "referenceId": "dup"},
        {"address": ADDR_A, "type": "SANCTIONED", "referenceId": "dup"},
    ]
    loaded = labels.LabelDataset.load(write(tmp_path, dataset(entries)))
    result = loaded.labels_for([ADDR_A])
    assert len(result) == 1
    assert result[0]["type"] == "OTHER"  # deterministic: sorted by referenceId then type


def test_ofac_source_is_carried_into_labels(tmp_path):
    entries = [{"address": ADDR_A, "type": "SANCTIONED", "referenceId": "OFAC-SDN-1"}]
    loaded = labels.LabelDataset.load(write(tmp_path, dataset(entries, source="OFAC_SDN")))
    assert loaded.labels_for([ADDR_A])[0]["source"] == "OFAC_SDN"


def test_non_mainnet_network_is_rejected_by_contract(tmp_path):
    loaded = labels.LabelDataset.load(write(tmp_path, dataset([{"address": ADDR_A, "type": "OTHER", "referenceId": "r"}])))
    with pytest.raises(ContractViolation):
        loaded.labels_for([ADDR_A], "devnet")


def test_invalid_entry_address_raises_value_error(tmp_path):
    path = write(tmp_path, dataset([{"address": "0OIl-not-base58", "type": "OTHER", "referenceId": "r"}]))
    with pytest.raises(ValueError) as info:
        labels.LabelDataset.load(path)
    assert not isinstance(info.value, CollectionError)


def test_short_decoded_address_raises_value_error(tmp_path):
    path = write(tmp_path, dataset([{"address": "2" * 32 + "3", "type": "OTHER", "referenceId": "r"}]))
    with pytest.raises(ValueError):
        labels.LabelDataset.load(path)


@pytest.mark.parametrize("data", [
    dataset([], source="UNKNOWN"),
    dataset([], version=""),
    dataset([], fetchedAt="yesterday"),
    dataset([{"address": ADDR_A, "type": "BAD", "referenceId": "r"}]),
    dataset([{"address": ADDR_A, "type": "OTHER", "referenceId": ""}]),
    dataset(None),
    dataset([], reference=7),
    ["not", "an", "object"],
])
def test_malformed_dataset_is_unavailable(tmp_path, data):
    with pytest.raises(CollectionError) as info:
        labels.LabelDataset.load(write(tmp_path, data))
    assert info.value.code == "UPSTREAM_UNAVAILABLE"
    assert info.value.status == 503
    assert info.value.retryable is False


def test_missing_file_is_unavailable(tmp_path):
    with pytest.raises(CollectionError) as info:
        labels.LabelDataset.load(tmp_path / "absent.json")
    assert info.value.code == "UPSTREAM_UNAVAILABLE"
    assert info.value.status == 503
    assert str(info.value) == "Label dataset unavailable"


def test_invalid_json_is_unavailable(tmp_path):
    with pytest.raises(CollectionError) as info:
        labels.LabelDataset.load(write(tmp_path, "{not json"))
    assert info.value.status == 503


def test_missing_default_file_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(labels, "DEFAULT_DATASET_PATH", tmp_path / "none.json")
    with pytest.raises(CollectionError):
        labels.LabelDataset.load()
