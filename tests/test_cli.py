from pathlib import Path
from unittest.mock import patch

from netlab.cli import main

EXAMPLE = Path(__file__).parents[1] / "examples/dual-wan.yml"


def test_validate_and_build(tmp_path):
    assert main(["validate", str(EXAMPLE)]) == 0
    assert main(["build", str(EXAMPLE), "--output", str(tmp_path / "lab")]) == 0
    assert main(["build", str(EXAMPLE), "--output", str(tmp_path / "lab")]) == 2


def test_invalid_input_has_clean_exit(tmp_path, capsys):
    file = tmp_path / "invalid.yml"
    file.write_text("[]")
    assert main(["validate", str(file)]) == 2
    assert "Error:" in capsys.readouterr().err


def test_missing_ansible_produces_incomplete_report(tmp_path, monkeypatch):
    out = tmp_path / "lab"
    main(["build", str(EXAMPLE), "--output", str(out)])
    monkeypatch.setenv("LAB_USERNAME", "test")
    monkeypatch.setenv("LAB_PASSWORD", "synthetic-password")
    playbook = Path(__file__).parents[1] / "ansible/verify.yml"
    with patch("netlab.cli.subprocess.run", side_effect=FileNotFoundError):
        assert (
            main(
                [
                    "verify",
                    str(out),
                    "--playbook",
                    str(playbook),
                    "--reports",
                    str(tmp_path / "reports"),
                ]
            )
            == 1
        )
    reports = list((tmp_path / "reports").glob("*/report.md"))
    assert len(reports) == 1
    assert "incomplete" in reports[0].read_text()
