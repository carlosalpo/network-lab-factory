import json

import pytest

from netlab.report import evaluate

MANIFEST = {
    "lab": "test",
    "scenario_sha256": "sample",
    "expected": {"r1": {"neighbors": ["198.19.0.2"], "targets": ["198.19.0.2"]}},
}


def evidence(directory, **overrides):
    record = {
        "host": "r1",
        "run_id": "run-1",
        "scenario_sha256": "sample",
        "neighbors": {
            "stdout": [
                (
                    "Neighbor ID Pri State Dead Time Address Interface\n"
                    "198.19.0.2 0 FULL/- 00:00:32 198.18.0.2 Gi0/1"
                )
            ]
        },
        "pings": {
            "results": [
                {
                    "item": "198.19.0.2",
                    "stdout": [
                        "!!!!!\nSuccess rate is 100 percent (5/5), round-trip min/avg/max = 1/2/3 ms"
                    ],
                }
            ]
        },
    }
    record.update(overrides)
    (directory / "r1.json").write_text(json.dumps(record))


def test_complete_evidence_passes(tmp_path):
    evidence(tmp_path)
    assert evaluate(MANIFEST, tmp_path, "run-1")["status"] == "passed"


def test_ios_spaced_point_to_point_state_passes(tmp_path):
    evidence(
        tmp_path,
        neighbors={
            "stdout": ["198.19.0.2          0   FULL/  -        00:00:32   198.18.0.2  Gi0/1"]
        },
    )
    assert evaluate(MANIFEST, tmp_path, "run-1")["status"] == "passed"


@pytest.mark.parametrize(
    "overrides",
    [
        {"run_id": "old-run"},
        {"scenario_sha256": "other-design"},
        {"host": "r2"},
        {"neighbors": {"failed": True}},
        {"neighbors": {"unreachable": True}},
        {"neighbors": {"stdout": []}},
        {"pings": {"results": []}},
        {"pings": None},
        {"pings": {"results": None}},
        {"pings": {"results": [{"item": "198.19.0.2", "stdout": ["% Invalid input"]}]}},
    ],
)
def test_missing_or_stale_evidence_never_passes(tmp_path, overrides):
    evidence(tmp_path, **overrides)
    assert evaluate(MANIFEST, tmp_path, "run-1")["status"] == "incomplete"


def test_unreachable_host_has_unknown_checks(tmp_path):
    result = evaluate(MANIFEST, tmp_path, "run-1")
    assert result["status"] == "incomplete"
    assert all(c["status"] == "unknown" for c in result["checks"])


def test_packet_loss_is_a_failure(tmp_path):
    evidence(
        tmp_path,
        pings={"results": [{"item": "198.19.0.2", "stdout": ["Success rate is 80 percent (4/5)"]}]},
    )
    assert evaluate(MANIFEST, tmp_path, "run-1")["status"] == "failed"


def test_non_full_neighbor_is_a_failure(tmp_path):
    evidence(tmp_path, neighbors={"stdout": ["198.19.0.2 0 INIT/- 00:00:32 198.18.0.2 Gi0/1"]})
    assert evaluate(MANIFEST, tmp_path, "run-1")["status"] == "failed"


def test_corrupt_json_is_unknown(tmp_path):
    (tmp_path / "r1.json").write_text("bad json")
    assert evaluate(MANIFEST, tmp_path, "run-1")["status"] == "incomplete"
