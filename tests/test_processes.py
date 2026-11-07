import json
from pathlib import Path
import subprocess
import sys
import queue
import threading
from http.client import HTTPConnection

import pytest

from compliance_contracts.runtime import ROOT, read_json

REPOSITORY = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("module,operation,scenario,expected", [
    ("kyt_engine", "evaluation-request", "sanctioned", "evaluation"),
    ("policy_engine", "policy-request", "sanctioned", "decision"),
])
def test_independent_module_process(module, operation, scenario, expected):
    process = subprocess.run([sys.executable, "-m", module, "--input", str(ROOT / f"fixtures/{scenario}/{operation}.json")],
                             cwd=REPOSITORY, capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == read_json(f"fixtures/{scenario}/{expected}.json")


@pytest.mark.parametrize("module,other", [("kyt_engine", "policy_engine"), ("policy_engine", "kyt_engine")])
def test_imports_are_independent(module, other):
    process = subprocess.run([sys.executable, "-c", f"import sys; import {module}; assert '{other}' not in sys.modules"],
                             capture_output=True, text=True, timeout=15)
    assert process.returncode == 0, process.stderr


def test_cli_stdin_and_error_exit(fixture_json):
    request = fixture_json("normal/evaluation-request.json")
    valid = subprocess.run([sys.executable, "-m", "kyt_engine", "--input", "-"], input=json.dumps(request),
                           capture_output=True, text=True, timeout=15)
    assert valid.returncode == 0 and json.loads(valid.stdout)["riskScore"] == 0
    invalid = subprocess.run([sys.executable, "-m", "kyt_engine", "--input", "-"], input='{"x":1,"x":2}',
                             capture_output=True, text=True, timeout=15)
    assert invalid.returncode != 0
    assert json.loads(invalid.stderr)["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize("scenario,action", [("normal", "ALLOW"), ("warn", "WARN"), ("partial", "REVIEW"), ("sanctioned", "BLOCK")])
def test_pipeline_demo_process(scenario, action):
    process = subprocess.run([sys.executable, "scripts/demo_engines.py", "--scenario", scenario], cwd=REPOSITORY,
                             capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert process.returncode == 0, process.stderr
    output = json.loads(process.stdout)
    assert output["decision"]["action"] == action
    assert output["gatewayRequest"]["decision"] == output["decision"]


def test_contract_validation_command():
    process = subprocess.run([sys.executable, "contracts/validate.py"], cwd=REPOSITORY,
                             capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stderr
    assert "151 fixtures" in process.stdout


@pytest.mark.parametrize("module,service", [("kyt_engine", "kyt-engine"), ("policy_engine", "policy-engine")])
def test_independent_http_server_process(module, service):
    process = subprocess.Popen([sys.executable, "-m", module, "--port", "0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = queue.Queue()
    reader = threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
    reader.start()
    try:
        line = lines.get(timeout=10)
        assert line.startswith(service + " 1.0.0 http://127.0.0.1:"), line
        port = int(line.rsplit(":", 1)[1])
        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("GET", "/health")
            response = connection.getresponse()
            assert response.status == 200
            assert json.loads(response.read())["service"] == service
        finally:
            connection.close()
    finally:
        process.terminate()
        process.wait(timeout=5)
        reader.join(timeout=5)
        process.stdout.close()
        process.stderr.close()
