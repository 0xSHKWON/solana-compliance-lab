"""Build the OFAC SDN label dataset from the official SDN XML export.

Usage:
  python -m collector.ofac                      # download from OFAC and write the default dataset file
  python -m collector.ofac --input SDN.XML      # parse a previously downloaded export (offline)

Only "Digital Currency Address - SOL" identifiers are extracted. The output keeps the SDN entry UID
as referenceId so every label can be traced back to the original list entry.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from pathlib import Path

from compliance_contracts.runtime import base58_size

from .labels import DEFAULT_DATASET_PATH

SDN_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML"
SOL_ID_TYPE = "Digital Currency Address - SOL"


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child(element, name):
    return next((child for child in element if _local(child.tag) == name), None)


def _text(element, name):
    child = _child(element, name)
    return (child.text or "").strip() if child is not None else ""


def parse_sdn_xml(raw: bytes, fetched_at: str, reference: str | None = SDN_URL) -> dict:
    root = ElementTree.fromstring(raw)
    publish = next((el for el in root.iter() if _local(el.tag) == "publshInformation"), None)
    publish_date = _text(publish, "Publish_Date") if publish is not None else ""
    if not publish_date:
        raise ValueError("SDN export has no Publish_Date")
    version = datetime.strptime(publish_date, "%m/%d/%Y").strftime("%Y-%m-%d")
    entries = {}
    for sdn in (el for el in root.iter() if _local(el.tag) == "sdnEntry"):
        uid = _text(sdn, "uid")
        id_list = _child(sdn, "idList")
        if not uid or id_list is None:
            continue
        for identifier in id_list:
            if _text(identifier, "idType") != SOL_ID_TYPE:
                continue
            address = _text(identifier, "idNumber")
            try:
                valid = base58_size(address) == 32
            except ValueError:
                valid = False
            if not valid:
                print(f"skipping invalid SOL address in SDN entry {uid}", file=sys.stderr)
                continue
            key = (address, uid)
            entries[key] = {"address": address, "type": "SANCTIONED", "referenceId": f"OFAC-SDN-{uid}"}
    return {
        "source": "OFAC_SDN",
        "version": version,
        "fetchedAt": fetched_at,
        "reference": reference,
        "entries": [entries[key] for key in sorted(entries)],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Refresh the OFAC SDN Solana label dataset")
    parser.add_argument("--input", help="Local SDN.XML file instead of downloading")
    parser.add_argument("--output", default=str(DEFAULT_DATASET_PATH))
    parser.add_argument("--allow-empty", action="store_true", help="Write the dataset even with zero SOL entries")
    args = parser.parse_args(argv)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if args.input:
        raw = Path(args.input).read_bytes()
    else:
        with urllib.request.urlopen(SDN_URL, timeout=120) as response:  # noqa: S310 - fixed official URL
            raw = response.read()
    dataset = parse_sdn_xml(raw, fetched_at)
    if not dataset["entries"] and not args.allow_empty:
        # A format change (e.g. a renamed idType) must not silently replace the dataset with an empty one.
        print("refusing to write: no SOL addresses found in the SDN export (use --allow-empty to override)",
              file=sys.stderr)
        return 1
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, output)  # readers never see a half-written dataset
    print(f"OFAC SDN {dataset['version']}: {len(dataset['entries'])} SOL addresses -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
