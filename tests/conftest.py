from copy import deepcopy

import pytest

from compliance_contracts.runtime import read_json
from kyt_engine import Detector
from policy_engine import PolicyEngine


@pytest.fixture
def detector():
    return Detector()


@pytest.fixture
def policy():
    return PolicyEngine()


@pytest.fixture
def fixture_json():
    return lambda path: deepcopy(read_json("fixtures/" + path))


@pytest.fixture
def sync_snapshot():
    def sync(request):
        snapshot = request["snapshot"]
        snapshot["coverage"]["transferCount"] = len(snapshot["transfers"])
        snapshot["coverage"]["transactionCount"] = len({row["signature"] for row in snapshot["transfers"]})
        return request
    return sync
