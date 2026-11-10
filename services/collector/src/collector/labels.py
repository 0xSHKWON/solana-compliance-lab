"""Address label dataset (OFAC SDN or test fixture) loaded from a local JSON file."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from pathlib import Path

from compliance_contracts.runtime import ContractViolation, base58_size, validate

from .errors import CollectionError

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATASET_PATH = REPO_ROOT / "services" / "collector" / "data" / "labels" / "ofac-sdn.json"
DATASET_ENV = "COLLECTOR_LABEL_DATASET"
DEFAULT_NETWORK = "mainnet-beta"

_ADDRESS_PATTERN = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
_SEVERITY = {"SANCTIONED": 0, "INCIDENT": 1, "OTHER": 2}
_LABEL_TYPES = frozenset(_SEVERITY)
_SOURCES = frozenset({"OFAC_SDN", "TEST_FIXTURE"})


def resolve_dataset_path(path=None) -> Path:
    """Explicit path, else COLLECTOR_LABEL_DATASET, else the default dataset file."""
    if path:
        return Path(path)
    configured = os.environ.get(DATASET_ENV)
    return Path(configured) if configured else DEFAULT_DATASET_PATH


def _unavailable() -> CollectionError:
    return CollectionError("Label dataset unavailable", "UPSTREAM_UNAVAILABLE", 503, False)


def _is_address(value) -> bool:
    if not isinstance(value, str) or _ADDRESS_PATTERN.fullmatch(value) is None:
        return False
    return base58_size(value) == 32


class LabelDataset:
    """Immutable set of (address, type, referenceId) entries sharing one source and version."""

    def __init__(self, *, source, version, fetched_at, reference, entries):
        self._source = source
        self._version = version
        self._fetched_at = fetched_at
        self._reference = reference
        # One label per (address, referenceId). If the same reference carries several types, the most
        # severe one wins so a SANCTIONED entry is never hidden behind INCIDENT/OTHER.
        ordered = sorted(set(entries), key=lambda e: (e[0], e[2], _SEVERITY[e[1]]))
        unique, seen = [], set()
        for address, label_type, reference_id in ordered:
            if (address, reference_id) not in seen:
                seen.add((address, reference_id))
                unique.append((address, label_type, reference_id))
        self._entries = tuple(unique)

    @classmethod
    def load(cls, path=None) -> "LabelDataset":
        target = resolve_dataset_path(path)
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            raise _unavailable() from None
        return cls.from_mapping(data)

    @classmethod
    def from_mapping(cls, data) -> "LabelDataset":
        if not isinstance(data, dict):
            raise _unavailable()
        metadata = {key: data.get(key) for key in ("source", "version", "fetchedAt")}
        reference, raw_entries = data.get("reference"), data.get("entries")
        if not isinstance(raw_entries, list) or (reference is not None and not isinstance(reference, str)):
            raise _unavailable()
        try:
            validate("collector", "LabelDataset", metadata)
        except ContractViolation:
            raise _unavailable() from None
        entries = [_parse_entry(raw) for raw in raw_entries]
        return cls(source=metadata["source"], version=metadata["version"], fetched_at=metadata["fetchedAt"],
                   reference=reference, entries=entries)

    def reference(self) -> str | None:
        """Where the dataset was obtained (e.g. the official SDN export URL)."""
        return self._reference

    def metadata(self) -> dict:
        return {"source": self._source, "version": self._version, "fetchedAt": self._fetched_at}

    def labels_for(self, addresses: Iterable[str], network: str = DEFAULT_NETWORK) -> list[dict]:
        wanted = set(addresses)
        labels = []
        for address, label_type, reference_id in self._entries:
            if address not in wanted:
                continue
            label = {"address": address, "network": network, "type": label_type,
                     "source": self._source, "referenceId": reference_id}
            validate("collector", "AddressLabel", label)
            labels.append(label)
        return labels


def _parse_entry(raw):
    if not isinstance(raw, dict):
        raise _unavailable()
    label_type, reference_id = raw.get("type"), raw.get("referenceId")
    if label_type not in _LABEL_TYPES or not isinstance(reference_id, str) or not reference_id:
        raise _unavailable()
    if not _is_address(raw.get("address")):
        raise _unavailable()  # a corrupt dataset is unusable, not a server crash
    return (raw["address"], label_type, reference_id)
