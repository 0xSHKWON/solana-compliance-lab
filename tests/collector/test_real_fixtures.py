"""Committed real mainnet fixtures: completeness, provenance and secret hygiene."""
import json
from pathlib import Path

import pytest

REAL_ROOT = Path(__file__).resolve().parents[2] / "services" / "collector" / "fixtures"
REQUIRED_FILES = ("snapshot.json", "collection-request.json", "rpc-recording.json", "source.json")
FORBIDDEN = ("nodit.io", "api-key", "x-api-key")
DIRECTORIES = sorted(path for path in REAL_ROOT.iterdir() if path.is_dir())


def load(directory, name):
    return json.loads((directory / name).read_text(encoding="utf-8"))


def test_real_fixture_directories_are_discovered():
    assert {path.name for path in DIRECTORIES} >= {"mainnet-normal-wallet", "mainnet-ofac-sdn-exact",
                                                    "mainnet-busy-wallet-partial", "mainnet-rapid-fan-out"}


@pytest.mark.parametrize("directory", DIRECTORIES, ids=lambda p: p.name)
def test_every_fixture_has_the_four_required_files(directory):
    for name in REQUIRED_FILES:
        assert (directory / name).is_file(), f"{directory.name} is missing {name}"


@pytest.mark.parametrize("directory", DIRECTORIES, ids=lambda p: p.name)
def test_snapshot_provenance_is_on_chain(directory):
    snapshot = load(directory, "snapshot.json")

    assert snapshot["dataProvenance"]["dataType"] == "ON_CHAIN"


@pytest.mark.parametrize("directory", DIRECTORIES, ids=lambda p: p.name)
def test_source_lists_explorer_links_for_transactions(directory):
    source = load(directory, "source.json")

    assert source["dataType"] == "ON_CHAIN"
    assert source["transactions"], "source.json must list the captured transactions"
    for transaction in source["transactions"]:
        assert transaction["explorer"] == f"https://explorer.solana.com/tx/{transaction['signature']}"
    assert source["address"]["explorer"].startswith("https://explorer.solana.com/address/")


@pytest.mark.parametrize("directory", DIRECTORIES, ids=lambda p: p.name)
def test_no_file_leaks_provider_host_or_api_key(directory):
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        text = path.read_text(encoding="utf-8").lower()
        for needle in FORBIDDEN:
            assert needle not in text, f"{path.relative_to(REAL_ROOT)} contains {needle!r}"
