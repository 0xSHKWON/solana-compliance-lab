"""OFAC SDN parsing and the committed SOL label dataset."""
import json

import pytest

from collector.labels import DEFAULT_DATASET_PATH, LabelDataset
from collector.ofac import SDN_URL, parse_sdn_xml
from compliance_contracts.runtime import validate

SOL_ADDRESS = "42RLPACwZPx3vYYmxSueqsogfynBDqXK298EDsNoyoHi"
ETH_ADDRESS = "0x1234567890abcdef1234567890abcdef12345678"
BAD_SOL = "not-a-solana-address!"
FETCHED_AT = "2026-11-10T00:00:00Z"

SDN_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<sdnList xmlns="https://tempuri.org/sdnList.xsd">
  <publshInformation>
    <Publish_Date>11/09/2026</Publish_Date>
    <Record_Count>3</Record_Count>
  </publshInformation>
  <sdnEntry>
    <uid>56360</uid>
    <lastName>EXAMPLE ONE</lastName>
    <sdnType>Individual</sdnType>
    <idList>
      <id>
        <uid>1001</uid>
        <idType>Digital Currency Address - SOL</idType>
        <idNumber>{SOL_ADDRESS}</idNumber>
      </id>
    </idList>
  </sdnEntry>
  <sdnEntry>
    <uid>70000</uid>
    <lastName>EXAMPLE TWO</lastName>
    <sdnType>Entity</sdnType>
    <idList>
      <id>
        <uid>1002</uid>
        <idType>Digital Currency Address - ETH</idType>
        <idNumber>{ETH_ADDRESS}</idNumber>
      </id>
      <id>
        <uid>1003</uid>
        <idType>Digital Currency Address - SOL</idType>
        <idNumber>{BAD_SOL}</idNumber>
      </id>
    </idList>
  </sdnEntry>
</sdnList>
""".encode("utf-8")


def test_parse_keeps_only_valid_sol_addresses(capsys):
    dataset = parse_sdn_xml(SDN_XML, FETCHED_AT)

    assert dataset == {
        "source": "OFAC_SDN",
        "version": "2026-11-09",
        "fetchedAt": FETCHED_AT,
        "reference": SDN_URL,
        "entries": [{"address": SOL_ADDRESS, "type": "SANCTIONED", "referenceId": "OFAC-SDN-56360"}],
    }
    assert "70000" in capsys.readouterr().err  # the invalid SOL string is reported, not silently dropped


def test_parse_accepts_explicit_reference():
    dataset = parse_sdn_xml(SDN_XML, FETCHED_AT, reference=None)

    assert dataset["reference"] is None


def test_missing_publish_date_is_rejected():
    raw = SDN_XML.replace(b"<Publish_Date>11/09/2026</Publish_Date>", b"")

    with pytest.raises(ValueError):
        parse_sdn_xml(raw, FETCHED_AT)


def test_missing_publication_block_is_rejected():
    raw = b"<sdnList><sdnEntry><uid>1</uid></sdnEntry></sdnList>"

    with pytest.raises(ValueError):
        parse_sdn_xml(raw, FETCHED_AT)


def test_committed_ofac_dataset_loads_and_every_entry_is_a_valid_label():
    raw = json.loads(DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))
    dataset = LabelDataset.load(DEFAULT_DATASET_PATH)

    assert dataset.metadata()["source"] == "OFAC_SDN"
    labels = dataset.labels_for([entry["address"] for entry in raw["entries"]])
    assert len(labels) == len(raw["entries"]) > 0
    for label in labels:
        validate("collector", "AddressLabel", label)
        assert label["source"] == "OFAC_SDN"
        assert label["referenceId"].startswith("OFAC-SDN-")
