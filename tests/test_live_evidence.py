"""Replay sanitized IOSv evidence to guard against device-output parser regressions."""

import json
from pathlib import Path

import pytest

from netlab.build import fingerprint
from netlab.model import load
from netlab.report import evaluate


@pytest.mark.parametrize(
    "phase,status,passed,failed",
    [("baseline", "passed", 20, 0), ("fault", "failed", 18, 2), ("recovery", "passed", 20, 0)],
)
def test_recorded_iosv_evidence(phase, status, passed, failed):
    root = Path(__file__).parents[1] / "docs/evidence/2026-10-29"
    manifest = json.loads((root / "manifest.json").read_text())
    recorded = json.loads((root / phase / "report.json").read_text())
    assert fingerprint(load(root / "scenario.yml")) == manifest["scenario_sha256"]
    result = evaluate(manifest, root / phase, recorded["run_id"])
    assert result["status"] == status
    assert result["checks"] == recorded["checks"]
    assert sum(c["status"] == "passed" for c in result["checks"]) == passed
    assert sum(c["status"] == "failed" for c in result["checks"]) == failed
    assert recorded["ansible_exit_code"] == 0
